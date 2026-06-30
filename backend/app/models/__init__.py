"""Model registry. Importing this package registers all 23 tables on
``Base.metadata`` for ``create_all``.
"""

from app.models.base import Base
from app.models.participant import Participant, ParticipantIdentity
from app.models.session import StudyCondition, StudySession
from app.models.dtt import (
    DttLoop,
    DttPerformanceEvent,
    DttPhase,
    DttProtocol,
    DttTrial,
)
from app.models.signals import (
    MediaRecording,
    ParticipantSelfReport,
    PerceptionEvent,
    RobotEvent,
    SelfReportDraft,
)
from app.models.questionnaire import (
    Questionnaire,
    QuestionnaireResponse,
    QuestionnaireScore,
)
from app.models.system import (
    Annotation,
    ExperimenterNote,
    Export,
    SessionTimelineEvent,
    SystemHealthEvent,
)
from app.models.sync import SyncGate

__all__ = [
    "Base",
    # participant
    "Participant",
    "ParticipantIdentity",
    # session
    "StudySession",
    "StudyCondition",
    # dtt
    "DttProtocol",
    "DttPhase",
    "DttLoop",
    "DttTrial",
    "DttPerformanceEvent",
    # signals
    "RobotEvent",
    "ParticipantSelfReport",
    "SelfReportDraft",
    "PerceptionEvent",
    "MediaRecording",
    # questionnaire
    "Questionnaire",
    "QuestionnaireResponse",
    "QuestionnaireScore",
    # system
    "SessionTimelineEvent",
    "ExperimenterNote",
    "SystemHealthEvent",
    "Export",
    "Annotation",
    # sync
    "SyncGate",
]
