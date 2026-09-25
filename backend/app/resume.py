"""Turn uploaded resumes into text and a structured candidate profile."""

import io
import re

from pydantic import BaseModel, Field

from .llm import run_structured


def extract_text(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    if name.endswith(".docx"):
        from docx import Document

        doc = Document(io.BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs).strip()
    if name.endswith((".txt", ".md")):
        return data.decode("utf-8", errors="replace").strip()
    raise ValueError("Unsupported file type; upload a PDF, DOCX, TXT, or MD resume")


class CandidateProfile(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    headline: str | None = Field(None, description="One-line professional summary, e.g. 'Senior backend engineer, 8 yrs Python'")
    skills: list[str] = Field(default_factory=list, description="Concrete technical and domain skills")
    years_experience: float | None = None


SYSTEM = """You extract structured candidate profiles from resumes for a recruiting system.
Only report facts stated in the resume. Leave a field null when the resume does not state it.
Normalize skill names to their common form (e.g. "postgres" -> "PostgreSQL")."""

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
_YEARS = re.compile(r"(\d{1,2})\+?\s*(?:years|yrs)", re.I)
COMMON_SKILLS = [
    "Python", "Java", "JavaScript", "TypeScript", "Go", "Rust", "C++", "C#", "Ruby", "PHP", "Kotlin", "Swift",
    "React", "Vue", "Angular", "Next.js", "Node.js", "FastAPI", "Django", "Flask", "Spring", "Rails",
    "PostgreSQL", "MySQL", "MongoDB", "Redis", "Kafka", "Elasticsearch", "SQL",
    "AWS", "GCP", "Azure", "Docker", "Kubernetes", "Terraform", "CI/CD", "Linux",
    "Machine Learning", "Deep Learning", "PyTorch", "TensorFlow", "NLP", "LLM", "Data Engineering", "Spark",
    "Figma", "Product Management", "Agile", "Scrum", "Sales", "Marketing", "Recruiting",
]


def find_skills(text: str) -> list[str]:
    lower = text.lower()
    return [s for s in COMMON_SKILLS if re.search(rf"(?<![a-z]){re.escape(s.lower())}(?![a-z])", lower)]


def _heuristic_profile(text: str) -> CandidateProfile:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    email = _EMAIL.search(text)
    phone = _PHONE.search(text)
    years = [int(m) for m in _YEARS.findall(text)]
    return CandidateProfile(
        name=lines[0][:200] if lines else "Unknown candidate",
        email=email.group(0) if email else None,
        phone=phone.group(0).strip() if phone else None,
        headline=lines[1][:300] if len(lines) > 1 else None,
        skills=find_skills(text),
        years_experience=float(max(years)) if years else None,
    )


def parse_profile(text: str) -> CandidateProfile:
    return run_structured(
        agent="screening",
        system=SYSTEM,
        prompt=f"<resume>\n{text}\n</resume>\n\nExtract the candidate profile.",
        schema=CandidateProfile,
        heuristic=lambda: _heuristic_profile(text),
    )
