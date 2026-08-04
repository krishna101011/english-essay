DIMENSIONS = {
    "grammar": "Grammar checks sentence accuracy, punctuation, and agreement.",
    "vocab": "Vocabulary checks precision and variety of word choice.",
    "structure": "Structure checks organisation, paragraph flow, and support for ideas.",
    "clarity": "Clarity checks how easily a reader can follow your meaning.",
}


def score_band(score: float) -> str:
    if score >= 85:
        return "Strong foundation"
    if score >= 70:
        return "Developing well"
    if score >= 50:
        return "A useful next step"
    return "Start with one small improvement"


def score_guidance(score) -> dict | None:
    if score is None:
        return None
    dimensions = {"grammar": score.grammar_score, "vocab": score.vocab_score, "structure": score.structure_score, "clarity": score.clarity_score}
    next_dimension = min(dimensions, key=dimensions.get)
    actions = {
        "grammar": "Choose one grammar suggestion and explain the rule in your own words.",
        "vocab": "Replace one repeated general word with a more precise word from the suggestions.",
        "structure": "Check that each paragraph has one clear main idea and a link to the next.",
        "clarity": "Read one paragraph aloud and shorten the sentence that feels hardest to follow.",
    }
    return {"band": score_band(score.overall_score), "dimensions": DIMENSIONS, "next_action": actions[next_dimension], "next_dimension": next_dimension}
