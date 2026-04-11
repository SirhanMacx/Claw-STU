"""Check-for-understanding engine.

Assessment in Claw-STU is formative, not summative. The goal is never to
assign a grade — it is to know whether the student actually understood,
so the next pedagogical decision can be made in good faith.
"""

from clawstu.assessment.crq import ConstructedResponseQuestion, CRQResponse
from clawstu.assessment.evaluator import EvaluationResult, Evaluator
from clawstu.assessment.feedback import FeedbackGenerator
from clawstu.assessment.generator import AssessmentItem, AssessmentType, QuestionGenerator

__all__ = [
    "AssessmentItem",
    "AssessmentType",
    "CRQResponse",
    "ConstructedResponseQuestion",
    "EvaluationResult",
    "Evaluator",
    "FeedbackGenerator",
    "QuestionGenerator",
]
