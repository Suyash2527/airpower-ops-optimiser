from fastapi import APIRouter

from app.core.config import DATA_LABEL

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "data_label": DATA_LABEL}
