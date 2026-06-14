import {
  LOCAL_CLASSIFIER_VERSION,
  createSkippedClassifierResponse,
  createShownClassifierResponse,
  createTraceId,
  stableHash,
  validateClassifierRequest
} from "../shared/classifier-contract.js";

const TONAL_RULES = [
  {
    kind: "engagement_bait",
    label: "Engagement pattern",
    confidence: 0.88,
    reason:
      "The post asks readers for low-friction reactions, which can inflate engagement without adding context.",
    patterns: [
      /\bcomment\s+(yes|below|your|if)\b/i,
      /\bshare\s+this\b/i,
      /\blike\s+if\b/i,
      /\bthoughts\?\s*$/i,
      /\bagree\?\s*$/i
    ]
  },
  {
    kind: "humblebrag",
    label: "Achievement framing",
    confidence: 0.84,
    reason:
      "The post frames an achievement through humility or gratitude while still foregrounding the achievement.",
    patterns: [
      /\b(humbled|honou?red|grateful)\s+to\s+(announce|share|say)\b/i,
      /\bi'?m\s+(humbled|honou?red)\b/i,
      /\bafter\s+\d+\s+(years|months)\b.*\bproud\b/i
    ]
  },
  {
    kind: "fake_vulnerability",
    label: "Vulnerability framing",
    confidence: 0.82,
    reason:
      "The post uses a personal-disclosure setup that resolves into a polished career lesson.",
    patterns: [
      /\bi\s+almost\s+didn'?t\s+post\s+this\b/i,
      /\bthis\s+is\s+hard\s+to\s+share\b/i,
      /\bvulnerable\s+post\b/i
    ]
  },
  {
    kind: "ai_ghostwritten",
    label: "Generic AI-like phrasing",
    confidence: 0.81,
    reason:
      "The post leans on generic, template-like phrasing with little concrete detail.",
    patterns: [
      /\bin\s+today'?s\s+(fast[- ]paced|ever[- ]changing)\s+world\b/i,
      /\bleverage\s+synergies\b/i,
      /\bgame[- ]changer\b/i,
      /\bunlock\s+(your|the)\s+full\s+potential\b/i
    ]
  },
  {
    kind: "corporate_cliche",
    label: "Corporate cliche",
    confidence: 0.79,
    reason:
      "The post relies on stock corporate phrasing instead of specific evidence.",
    patterns: [
      /\bmove\s+fast\s+and\s+break\s+things\b/i,
      /\bdisrupt(?:ing)?\s+the\s+industry\b/i,
      /\bmission[- ]driven\b/i,
      /\bcustomer[- ]obsessed\b/i
    ]
  },
  {
    kind: "sycophancy",
    label: "Praise-heavy framing",
    confidence: 0.78,
    reason:
      "The post uses praise-heavy language without much supporting analysis.",
    patterns: [
      /\bincredible\s+leader(ship)?\b/i,
      /\bvisionary\s+leader\b/i,
      /\bso\s+inspired\s+by\b/i
    ]
  },
  {
    kind: "waffle",
    label: "Broad filler phrasing",
    confidence: 0.76,
    reason:
      "The post uses broad claims and filler phrasing without enough concrete substance.",
    patterns: [
      /\bthe\s+future\s+is\s+now\b/i,
      /\bit'?s\s+all\s+about\s+mindset\b/i,
      /\bjourney\s+of\s+growth\b/i
    ]
  }
];

function findRuleMatches(text) {
  const matches = [];

  for (const rule of TONAL_RULES) {
    const evidence = rule.patterns
      .map((pattern) => text.match(pattern)?.[0])
      .filter(Boolean);

    if (evidence.length > 0) {
      matches.push({
        rule,
        evidence
      });
    }
  }

  return matches.sort((left, right) => right.rule.confidence - left.rule.confidence);
}

export function classifyPostTone(request, options = {}) {
  const validation = validateClassifierRequest(request);

  if (!validation.ok) {
    return createSkippedClassifierResponse({
      request,
      skippedReason: "contract_validation_failed"
    });
  }

  const text = request.post.text;

  if (!text) {
    return createSkippedClassifierResponse({
      request,
      skippedReason: "empty_post"
    });
  }

  const [match] = findRuleMatches(text);

  if (!match) {
    return createSkippedClassifierResponse({
      request,
      skippedReason: "no_tonal_signal"
    });
  }

  const generatedAt = options.generatedAt ?? new Date().toISOString();
  const postId = request.post.id;
  const note = {
    traceId: createTraceId({
      requestId: request.requestId,
      postId,
      kind: match.rule.kind,
      generatedAt
    }),
    dedupeKey: `post:${stableHash(`${postId}:${match.rule.kind}`)}`,
    kind: match.rule.kind,
    label: match.rule.label,
    reason: match.rule.reason,
    confidence: match.rule.confidence,
    model: LOCAL_CLASSIFIER_VERSION,
    evidence: match.evidence.slice(0, 3),
    sources: [],
    generatedAt
  };

  if (note.confidence < request.settingsSnapshot.minimumConfidence) {
    return createSkippedClassifierResponse({
      request,
      skippedReason: "below_confidence_threshold",
      candidate: note
    });
  }

  return createShownClassifierResponse({
    request,
    note
  });
}
