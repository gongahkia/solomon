const TONAL_RULES = [
  {
    kind: "engagement_bait",
    label: "Engagement-bait",
    confidence: 0.88,
    reason:
      "The post asks for low-friction reactions instead of adding substantive context.",
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
    label: "Humblebrag",
    confidence: 0.84,
    reason:
      "The post frames self-promotion as humility or gratitude while foregrounding the achievement.",
    patterns: [
      /\b(humbled|honou?red|grateful)\s+to\s+(announce|share|say)\b/i,
      /\bi'?m\s+(humbled|honou?red)\b/i,
      /\bafter\s+\d+\s+(years|months)\b.*\bproud\b/i
    ]
  },
  {
    kind: "fake_vulnerability",
    label: "Fake vulnerability",
    confidence: 0.82,
    reason:
      "The post uses a vulnerability setup that resolves into a polished career lesson.",
    patterns: [
      /\bi\s+almost\s+didn'?t\s+post\s+this\b/i,
      /\bthis\s+is\s+hard\s+to\s+share\b/i,
      /\bvulnerable\s+post\b/i
    ]
  },
  {
    kind: "ai_ghostwritten",
    label: "AI-ghostwritten",
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
    label: "Sycophancy",
    confidence: 0.78,
    reason:
      "The post uses praise-heavy language that reads more like approval seeking than analysis.",
    patterns: [
      /\bincredible\s+leader(ship)?\b/i,
      /\bvisionary\s+leader\b/i,
      /\bso\s+inspired\s+by\b/i
    ]
  },
  {
    kind: "waffle",
    label: "Waffle",
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

function stableHash(input) {
  let hash = 2166136261;

  for (let index = 0; index < input.length; index += 1) {
    hash ^= input.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }

  return (hash >>> 0).toString(36);
}

function normalizeText(value) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

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

export function createTraceId(post, kind, timestamp = new Date().toISOString()) {
  const randomPart = crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
  const traceHash = stableHash(`${post.id}:${kind}:${timestamp}:${randomPart}`);
  return `trace:${traceHash}`;
}

export function classifyPostTone(post, options = {}) {
  const text = normalizeText(post?.text);

  if (!text) {
    return {
      note: null,
      skippedReason: "empty_post"
    };
  }

  const [match] = findRuleMatches(text);

  if (!match) {
    return {
      note: null,
      skippedReason: "no_tonal_signal"
    };
  }

  const generatedAt = options.generatedAt ?? new Date().toISOString();
  const postId = String(post.id ?? stableHash(text.slice(0, 500)));
  const note = {
    traceId: createTraceId({ id: postId }, match.rule.kind, generatedAt),
    dedupeKey: `post:${stableHash(`${postId}:${match.rule.kind}`)}`,
    kind: match.rule.kind,
    label: match.rule.label,
    reason: match.rule.reason,
    confidence: match.rule.confidence,
    model: "local-tonal-rules-v1",
    evidence: match.evidence.slice(0, 3),
    sources: [],
    generatedAt
  };

  return {
    note,
    skippedReason: null
  };
}
