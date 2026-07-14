// SPDX-License-Identifier: MIT

//! OIDC discovery, JWT validation, and privacy-safe principal mapping.

use jsonwebtoken::jwk::{Jwk, JwkSet, KeyAlgorithm, KeyOperations, PublicKeyUse};
use jsonwebtoken::{Algorithm, DecodingKey, Validation, decode, decode_header};
use reqwest::blocking::Client;
use reqwest::redirect::Policy;
use serde::Deserialize;
use serde_json::Value;
use std::fmt::{self, Display, Formatter};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use url::Url;

const KEY_REFRESH_INTERVAL: Duration = Duration::from_secs(300);
const CLOCK_SKEW_SECONDS: u64 = 30;
const PRINCIPAL_HASH_DOMAIN: &[u8] = b"shibahama:oidc:principal:v1";

/// OIDC settings required to authenticate one shared Shibahama service.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OidcConfig {
    /// Exact OIDC issuer URL.
    pub issuer: String,
    /// Required audience/client identifier.
    pub audience: String,
    /// Top-level string claim mapped to the internal principal.
    pub principal_claim: String,
}

impl OidcConfig {
    /// Creates validated OIDC settings.
    ///
    /// # Errors
    ///
    /// Returns an error for an insecure issuer, empty audience, or unsupported claim name.
    pub fn new(
        issuer: impl Into<String>,
        audience: impl Into<String>,
        principal_claim: impl Into<String>,
    ) -> Result<Self, OidcError> {
        let issuer = issuer.into();
        let audience = audience.into();
        let principal_claim = principal_claim.into();

        validate_issuer_url(&issuer)?;
        if audience.is_empty() || audience.len() > 256 || !valid_oidc_claim_name(&principal_claim) {
            return Err(OidcError::Configuration);
        }

        Ok(Self {
            issuer,
            audience,
            principal_claim,
        })
    }
}

/// OIDC authentication failure without raw token, claim, or remote-response content.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OidcError {
    /// Local OIDC configuration was invalid.
    Configuration,
    /// Provider discovery was unavailable or inconsistent with configured issuer metadata.
    Discovery,
    /// The provider key set was unavailable or did not contain a suitable signing key.
    KeySet,
    /// The bearer token was malformed, unsigned, expired, or had invalid claims.
    Unauthorized,
}

impl Display for OidcError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        let detail = match self {
            Self::Configuration => "OIDC configuration is invalid",
            Self::Discovery => "OIDC discovery failed",
            Self::KeySet => "OIDC key retrieval failed",
            Self::Unauthorized => "OIDC bearer authentication failed",
        };

        formatter.write_str(detail)
    }
}

impl std::error::Error for OidcError {}

/// Validates bearer tokens and maps their configured identity claim to an opaque principal.
#[derive(Clone)]
pub struct OidcAuthenticator {
    config: OidcConfig,
    jwks_url: Url,
    allowed_algorithms: Vec<Algorithm>,
    key_cache: Arc<Mutex<JwkCache>>,
    fetcher: Arc<dyn OidcDocumentFetcher>,
}

impl OidcAuthenticator {
    /// Discovers OIDC metadata and initializes the JWKS cache.
    ///
    /// # Errors
    ///
    /// Returns an error when discovery or the provider key set cannot be securely validated.
    pub fn discover(config: OidcConfig) -> Result<Self, OidcError> {
        let fetcher = Arc::new(HttpOidcDocumentFetcher::new()?);

        Self::discover_with_fetcher(config, fetcher)
    }

    fn discover_with_fetcher(
        config: OidcConfig,
        fetcher: Arc<dyn OidcDocumentFetcher>,
    ) -> Result<Self, OidcError> {
        let issuer_url = validate_issuer_url(&config.issuer)?;
        let discovery_url = discovery_url(&issuer_url);
        let discovery: OidcDiscoveryDocument =
            serde_json::from_value(fetcher.fetch_json(&discovery_url)?)
                .map_err(|_| OidcError::Discovery)?;

        if discovery.issuer != config.issuer {
            return Err(OidcError::Discovery);
        }
        let jwks_url = validate_https_url(&discovery.jwks_uri, OidcError::Discovery)?;
        let allowed_algorithms = discovery
            .id_token_signing_alg_values_supported
            .iter()
            .filter_map(|value| parse_oidc_algorithm(value))
            .collect::<Vec<_>>();
        if allowed_algorithms.is_empty() {
            return Err(OidcError::Discovery);
        }
        let jwks = fetch_jwks(fetcher.as_ref(), &jwks_url)?;

        Ok(Self {
            config,
            jwks_url,
            allowed_algorithms,
            key_cache: Arc::new(Mutex::new(JwkCache {
                jwks,
                fetched_at: Instant::now(),
            })),
            fetcher,
        })
    }

    /// Validates an OIDC bearer token and returns a stable opaque internal principal.
    ///
    /// # Errors
    ///
    /// Returns an error without exposing token or claim content.
    pub fn authenticate(&self, token: &str) -> Result<String, OidcError> {
        self.refresh_keys_if_stale()?;
        let header = decode_header(token).map_err(|_| OidcError::Unauthorized)?;
        let kid = header
            .kid
            .as_deref()
            .filter(|kid| valid_key_id(kid))
            .ok_or(OidcError::Unauthorized)?;
        if !self.allowed_algorithms.contains(&header.alg) {
            return Err(OidcError::Unauthorized);
        }
        let key = self.decoding_key(kid, header.alg)?;
        let mut validation = Validation::new(header.alg);

        validation.algorithms = vec![header.alg];
        validation.set_issuer(&[&self.config.issuer]);
        validation.set_audience(&[&self.config.audience]);
        validation.set_required_spec_claims(&["exp", "iss", "aud", "sub"]);
        validation.validate_nbf = true;
        validation.leeway = CLOCK_SKEW_SECONDS;

        let claims = decode::<Value>(token, &key, &validation)
            .map_err(|_| OidcError::Unauthorized)?
            .claims;
        validate_oidc_claim_shape(&claims, &self.config)?;
        let principal_value = claims
            .get(&self.config.principal_claim)
            .and_then(Value::as_str)
            .filter(|value| !value.is_empty() && value.len() <= 512)
            .ok_or(OidcError::Unauthorized)?;

        Ok(opaque_principal(
            &self.config.issuer,
            &self.config.principal_claim,
            principal_value,
        ))
    }

    fn refresh_keys_if_stale(&self) -> Result<(), OidcError> {
        let stale = self
            .key_cache
            .lock()
            .map_err(|_| OidcError::KeySet)?
            .fetched_at
            .elapsed()
            >= KEY_REFRESH_INTERVAL;

        if stale {
            self.refresh_keys()?;
        }

        Ok(())
    }

    fn decoding_key(&self, kid: &str, algorithm: Algorithm) -> Result<DecodingKey, OidcError> {
        if let Some(jwk) = self.find_key(kid, algorithm)? {
            return DecodingKey::from_jwk(&jwk).map_err(|_| OidcError::Unauthorized);
        }

        self.refresh_keys()?;
        let jwk = self
            .find_key(kid, algorithm)?
            .ok_or(OidcError::Unauthorized)?;

        DecodingKey::from_jwk(&jwk).map_err(|_| OidcError::Unauthorized)
    }

    fn find_key(&self, kid: &str, algorithm: Algorithm) -> Result<Option<Jwk>, OidcError> {
        let cache = self.key_cache.lock().map_err(|_| OidcError::KeySet)?;

        Ok(cache
            .jwks
            .keys
            .iter()
            .find(|jwk| jwk_is_eligible(jwk, kid, algorithm))
            .cloned())
    }

    fn refresh_keys(&self) -> Result<(), OidcError> {
        let jwks = fetch_jwks(self.fetcher.as_ref(), &self.jwks_url)?;
        let mut cache = self.key_cache.lock().map_err(|_| OidcError::KeySet)?;

        cache.jwks = jwks;
        cache.fetched_at = Instant::now();

        Ok(())
    }
}

struct JwkCache {
    jwks: JwkSet,
    fetched_at: Instant,
}

trait OidcDocumentFetcher: Send + Sync {
    fn fetch_json(&self, url: &Url) -> Result<Value, OidcError>;
}

struct HttpOidcDocumentFetcher {
    client: Client,
}

impl HttpOidcDocumentFetcher {
    fn new() -> Result<Self, OidcError> {
        let client = Client::builder()
            .https_only(true)
            .redirect(Policy::none())
            .timeout(Duration::from_secs(5))
            .build()
            .map_err(|_| OidcError::Configuration)?;

        Ok(Self { client })
    }
}

impl OidcDocumentFetcher for HttpOidcDocumentFetcher {
    fn fetch_json(&self, url: &Url) -> Result<Value, OidcError> {
        self.client
            .get(url.clone())
            .send()
            .map_err(|_| OidcError::Discovery)?
            .error_for_status()
            .map_err(|_| OidcError::Discovery)?
            .json()
            .map_err(|_| OidcError::Discovery)
    }
}

#[derive(Deserialize)]
struct OidcDiscoveryDocument {
    issuer: String,
    jwks_uri: String,
    id_token_signing_alg_values_supported: Vec<String>,
}

fn fetch_jwks(fetcher: &dyn OidcDocumentFetcher, url: &Url) -> Result<JwkSet, OidcError> {
    let document = fetcher.fetch_json(url).map_err(|_| OidcError::KeySet)?;
    let jwks: JwkSet = serde_json::from_value(document).map_err(|_| OidcError::KeySet)?;

    if jwks.keys.is_empty() {
        Err(OidcError::KeySet)
    } else {
        Ok(jwks)
    }
}

fn validate_issuer_url(value: &str) -> Result<Url, OidcError> {
    let issuer = validate_https_url(value, OidcError::Configuration)?;

    if issuer.query().is_some()
        || issuer.fragment().is_some()
        || !issuer.username().is_empty()
        || issuer.password().is_some()
    {
        return Err(OidcError::Configuration);
    }

    Ok(issuer)
}

fn validate_https_url(value: &str, error: OidcError) -> Result<Url, OidcError> {
    let url = Url::parse(value).map_err(|_| error)?;

    if url.scheme() != "https" || url.host_str().is_none() || url.fragment().is_some() {
        return Err(error);
    }

    Ok(url)
}

fn discovery_url(issuer: &Url) -> Url {
    let mut url = issuer.clone();
    let issuer_path = issuer.path().trim_end_matches('/');

    url.set_path(&format!("/.well-known/openid-configuration{issuer_path}"));
    url.set_query(None);
    url.set_fragment(None);

    url
}

fn parse_oidc_algorithm(value: &str) -> Option<Algorithm> {
    match value {
        "RS256" => Some(Algorithm::RS256),
        "RS384" => Some(Algorithm::RS384),
        "RS512" => Some(Algorithm::RS512),
        "PS256" => Some(Algorithm::PS256),
        "PS384" => Some(Algorithm::PS384),
        "PS512" => Some(Algorithm::PS512),
        "ES256" => Some(Algorithm::ES256),
        "ES384" => Some(Algorithm::ES384),
        "EdDSA" => Some(Algorithm::EdDSA),
        _ => None,
    }
}

fn key_algorithm_for(algorithm: Algorithm) -> KeyAlgorithm {
    match algorithm {
        Algorithm::HS256 => KeyAlgorithm::HS256,
        Algorithm::HS384 => KeyAlgorithm::HS384,
        Algorithm::HS512 => KeyAlgorithm::HS512,
        Algorithm::ES256 => KeyAlgorithm::ES256,
        Algorithm::ES384 => KeyAlgorithm::ES384,
        Algorithm::RS256 => KeyAlgorithm::RS256,
        Algorithm::RS384 => KeyAlgorithm::RS384,
        Algorithm::RS512 => KeyAlgorithm::RS512,
        Algorithm::PS256 => KeyAlgorithm::PS256,
        Algorithm::PS384 => KeyAlgorithm::PS384,
        Algorithm::PS512 => KeyAlgorithm::PS512,
        Algorithm::EdDSA => KeyAlgorithm::EdDSA,
    }
}

fn jwk_is_eligible(jwk: &Jwk, kid: &str, algorithm: Algorithm) -> bool {
    jwk.common.key_id.as_deref() == Some(kid)
        && jwk
            .common
            .public_key_use
            .as_ref()
            .is_none_or(|usage| *usage == PublicKeyUse::Signature)
        && jwk
            .common
            .key_operations
            .as_ref()
            .is_none_or(|operations| operations.contains(&KeyOperations::Verify))
        && jwk
            .common
            .key_algorithm
            .is_none_or(|key_algorithm| key_algorithm == key_algorithm_for(algorithm))
}

fn validate_oidc_claim_shape(claims: &Value, config: &OidcConfig) -> Result<(), OidcError> {
    let now = i64::try_from(jsonwebtoken::get_current_timestamp())
        .map_err(|_| OidcError::Unauthorized)?;
    let issued_at = claims
        .get("iat")
        .and_then(Value::as_i64)
        .ok_or(OidcError::Unauthorized)?;

    if issued_at > now.saturating_add(i64::try_from(CLOCK_SKEW_SECONDS).unwrap_or(i64::MAX)) {
        return Err(OidcError::Unauthorized);
    }

    if claims
        .get("aud")
        .and_then(Value::as_array)
        .is_some_and(|audience| audience.len() > 1)
        && claims.get("azp").and_then(Value::as_str) != Some(config.audience.as_str())
    {
        return Err(OidcError::Unauthorized);
    }

    Ok(())
}

fn opaque_principal(issuer: &str, claim_name: &str, claim_value: &str) -> String {
    let mut hasher = blake3::Hasher::new();

    hasher.update(PRINCIPAL_HASH_DOMAIN);
    append_hash_field(&mut hasher, "issuer", issuer);
    append_hash_field(&mut hasher, "claim", claim_name);
    append_hash_field(&mut hasher, "value", claim_value);

    format!("oidc:{}", hasher.finalize().to_hex())
}

fn append_hash_field(hasher: &mut blake3::Hasher, name: &str, value: &str) {
    hasher.update(name.as_bytes());
    hasher.update(&[0]);
    hasher.update(value.len().to_string().as_bytes());
    hasher.update(&[0]);
    hasher.update(value.as_bytes());
    hasher.update(&[0xff]);
}

fn valid_oidc_claim_name(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
}

fn valid_key_id(value: &str) -> bool {
    !value.is_empty() && value.len() <= 256 && value.is_ascii()
}

#[cfg(test)]
mod tests {
    use super::{
        OidcAuthenticator, OidcConfig, OidcDocumentFetcher, OidcError, discovery_url,
        opaque_principal, validate_issuer_url,
    };
    use jsonwebtoken::jwk::{Jwk, KeyAlgorithm, PublicKeyUse};
    use jsonwebtoken::{Algorithm, EncodingKey, Header, encode};
    use serde_json::{Value, json};
    use std::sync::Arc;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use url::Url;

    const TEST_EC_PRIVATE_KEY: &[u8] = b"-----BEGIN PRIVATE KEY-----\nMIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgTGFmPAvYuwTc91PF\ng2T+cIa332e91YDWZ0hMVyMLSy+hRANCAAR9ks/G2eJO9unGHfPorXRF+R5SyttZ\nOEmJ2Az1qH2gTZR9Kp1NfRwCeJPig6D3+aKD3BvkasssNlroql3saXoh\n-----END PRIVATE KEY-----\n";

    struct FakeFetcher {
        discovery: Value,
        jwks_documents: Vec<Value>,
        jwks_reads: AtomicUsize,
    }

    impl OidcDocumentFetcher for FakeFetcher {
        fn fetch_json(&self, url: &Url) -> Result<Value, OidcError> {
            if url.path().starts_with("/.well-known/") {
                return Ok(self.discovery.clone());
            }
            let index = self.jwks_reads.fetch_add(1, Ordering::SeqCst);
            self.jwks_documents
                .get(index.min(self.jwks_documents.len().saturating_sub(1)))
                .cloned()
                .ok_or(OidcError::KeySet)
        }
    }

    fn signing_key() -> EncodingKey {
        EncodingKey::from_ec_pem(TEST_EC_PRIVATE_KEY).expect("test EC key should parse")
    }

    fn jwks_document(kid: &str) -> Value {
        let mut jwk = Jwk::from_encoding_key(&signing_key(), Algorithm::ES256)
            .expect("test EC JWK should build");
        jwk.common.key_id = Some(kid.to_owned());
        jwk.common.key_algorithm = Some(KeyAlgorithm::ES256);
        jwk.common.public_key_use = Some(PublicKeyUse::Signature);

        json!({ "keys": [jwk] })
    }

    fn token(issuer: &str, audience: &str, expires_at: u64) -> String {
        let mut header = Header::new(Algorithm::ES256);
        header.kid = Some("rotated-key".to_owned());
        let now = jsonwebtoken::get_current_timestamp();

        encode(
            &header,
            &json!({
                "iss": issuer,
                "sub": "alice@example.test",
                "aud": audience,
                "iat": now,
                "exp": expires_at,
            }),
            &signing_key(),
        )
        .expect("test token should sign")
    }

    fn authenticator() -> (OidcAuthenticator, Arc<FakeFetcher>) {
        let fetcher = Arc::new(FakeFetcher {
            discovery: json!({
                "issuer": "https://issuer.example/tenant",
                "jwks_uri": "https://issuer.example/keys",
                "id_token_signing_alg_values_supported": ["ES256"],
            }),
            jwks_documents: vec![jwks_document("old-key"), jwks_document("rotated-key")],
            jwks_reads: AtomicUsize::new(0),
        });
        let config = OidcConfig::new("https://issuer.example/tenant", "shibahama", "sub")
            .expect("OIDC config should validate");
        let authenticator = OidcAuthenticator::discover_with_fetcher(config, fetcher.clone())
            .expect("OIDC metadata should validate");

        (authenticator, fetcher)
    }

    #[test]
    fn discovery_uses_the_oidc_path_insertion_rule() {
        let issuer = validate_issuer_url("https://issuer.example/tenant/v1")
            .expect("issuer should validate");

        assert_eq!(
            discovery_url(&issuer).as_str(),
            "https://issuer.example/.well-known/openid-configuration/tenant/v1"
        );
    }

    #[test]
    fn oidc_configuration_requires_secure_exact_inputs() {
        assert!(matches!(
            OidcConfig::new("http://issuer.example", "service", "sub"),
            Err(OidcError::Configuration)
        ));
        assert!(matches!(
            OidcConfig::new("https://issuer.example?query=1", "service", "sub"),
            Err(OidcError::Configuration)
        ));
        assert!(matches!(
            OidcConfig::new("https://issuer.example", "", "sub"),
            Err(OidcError::Configuration)
        ));
    }

    #[test]
    fn opaque_principals_are_stable_and_hide_claim_values() {
        let principal = opaque_principal("https://issuer.example", "sub", "alice@example.test");

        assert_eq!(
            principal,
            opaque_principal("https://issuer.example", "sub", "alice@example.test")
        );
        assert_ne!(
            principal,
            opaque_principal("https://issuer.example", "sub", "bob@example.test")
        );
        assert!(!principal.contains("alice"));
        assert!(!principal.contains("issuer.example"));
    }

    #[test]
    fn oidc_refreshes_unknown_key_ids_and_enforces_registered_claims() {
        let (authenticator, fetcher) = authenticator();
        let now = jsonwebtoken::get_current_timestamp();
        let valid = token("https://issuer.example/tenant", "shibahama", now + 300);
        let principal = authenticator
            .authenticate(&valid)
            .expect("rotated signing key should authenticate after refresh");

        assert!(principal.starts_with("oidc:"));
        assert!(!principal.contains("alice"));
        assert_eq!(fetcher.jwks_reads.load(Ordering::SeqCst), 2);

        let wrong_issuer = token("https://other.example/tenant", "shibahama", now + 300);
        assert_eq!(
            authenticator.authenticate(&wrong_issuer),
            Err(OidcError::Unauthorized)
        );
        let wrong_audience = token("https://issuer.example/tenant", "other", now + 300);
        assert_eq!(
            authenticator.authenticate(&wrong_audience),
            Err(OidcError::Unauthorized)
        );
        let expired = token(
            "https://issuer.example/tenant",
            "shibahama",
            now.saturating_sub(31),
        );
        assert_eq!(
            authenticator.authenticate(&expired),
            Err(OidcError::Unauthorized)
        );
    }
}
