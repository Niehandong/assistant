"""导入全部模型，保证 Alembic autogenerate 能看到所有表。"""

from app.models.ai_model import SCHEMA, AiModel
from app.models.assignment import DatasetAssignment
from app.models.child_chunk import ChildChunk
from app.models.dataset import Dataset
from app.models.document import Document
from app.models.ref import OrgRef, UserRef
from app.models.retrieval_record import RetrievalRecord
from app.models.segment import Segment
from app.models.upload_file import UploadFile

__all__ = [
    "SCHEMA",
    "AiModel",
    "ChildChunk",
    "Dataset",
    "DatasetAssignment",
    "Document",
    "OrgRef",
    "RetrievalRecord",
    "Segment",
    "UploadFile",
    "UserRef",
]
