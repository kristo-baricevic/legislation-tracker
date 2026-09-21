"""Conservative, source-matched glossary explanations; never infer external law.

Reviewed paraphrases apply only to the complete matching definition, not its
term alone. Changed conditions fall back to labelled legal text for review.
"""

import re


def normalized(text):
    return re.sub(r"\s+", " ", text).strip().rstrip(".").casefold()


REVIEWED = [
    (
        "completion rate",
        "the percentage of students from an initial cohort enrolled at an entity that is a 2-year institution who have graduated from the institution or transferred to a 4-year institution of higher education; or the percentage of students from an initial cohort enrolled at an entity in the State that is a 4-year institution who have graduated from the institution",
        "The share of a starting group of students who finish: at a two-year college, graduation or transfer to a four-year college counts; at a four-year college in the state, graduation counts.",
    ),
    (
        "eligible entity",
        "a public institution of higher education; a partnership between a nonprofit educational organization and an institution of higher education; or a consortium of institutions of higher education",
        "Public colleges and universities, partnerships between nonprofit education organizations and colleges, or groups of colleges working together.",
    ),
    (
        "eligible Indian entity",
        "the entity responsible for the governance, operation, or control of a Tribal College or University",
        "The organization that governs, operates, or controls a Tribal College or University.",
    ),
    (
        "evidence tier 1 reform or practice",
        "a reform or practice that prior research suggests has promise for the purpose of successfully improving student achievement or attainment for high-need students",
        "An approach that earlier research suggests could improve achievement or educational attainment for high-need students. This is evidence of promise, not proof of success.",
    ),
    (
        "evidence tier 2 reform or practice",
        "a reform or practice described in subparagraph (A), or other reform or practice meeting similar criteria, that measures impact and cost effectiveness of student success activities, and, through rigorous evaluation (including through the use of existing administrative data, as applicable), has been found to be successfully implemented",
        "An approach meeting tier 1 or similar criteria that measures impact and cost-effectiveness and has been rigorously evaluated as successfully implemented. Successful implementation does not itself establish sizable impacts.",
    ),
    (
        "evidence tier 3 reform or practice",
        "a reform or practice described in subparagraph (B), or other reform or practice meeting similar criteria, that has been found to produce sizable, important impacts on student success and— determining whether such impacts can be successfully reproduced and sustained over time; and identifying the conditions in which such reform or practice is most effective",
        "An approach meeting tier 2 or similar criteria with sizable, important effects on student success. The source wording is unclear about its additional requirements concerning repeatability, lasting effects, and conditions for effectiveness; read the legal text before relying on this explanation.",
    ),
    (
        "high-need student",
        "a student from a low-income background; a first generation college student; a caregiver student; a student with a disability; a student who dropped out before completing; a reentering justice-impacted student; or a military-connected student",
        "A student in any of these groups: low-income, first-generation, a caregiver, disabled, left school before completing, returning after involvement with the justice system, or military-connected.",
    ),
    ("Secretary", "the Secretary of Education", "The U.S. Secretary of Education."),
]

PARAPHRASES = {
    (normalized(term), normalized(source)): explanation
    for term, source, explanation in REVIEWED
}


def explain_definition(term, definition, definition_type):
    if definition_type != "means":
        return f"{'Includes' if definition_type == 'includes' else 'Excludes'}: {definition.rstrip('.')}."
    if re.search(r"\bmeaning (?:given|assigned|provided)\b", definition, re.I):
        return f"Unresolved legal reference. This bill defines “{term}” by reference to another law; its meaning has not been verified here. Open the legal definition for the citation."
    return PARAPHRASES.get(
        (normalized(term), normalized(definition)),
        f"Legal definition: {definition.rstrip('.')}.",
    )
