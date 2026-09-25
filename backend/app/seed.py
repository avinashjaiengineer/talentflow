"""Load demo jobs and candidates:  python -m app.seed"""

from sqlalchemy import select

from .db import SessionLocal, init_db
from .embeddings import embed_one
from .models import Candidate, Job
from .resume import parse_profile

JOBS = [
    {
        "title": "Senior Backend Engineer",
        "department": "Engineering",
        "location": "Remote",
        "description": "Build and scale the APIs behind our hiring platform. You will own services end to end, "
        "from data modeling in PostgreSQL to deployment on Kubernetes, and mentor two mid-level engineers.",
        "requirements": ["5+ years backend development", "Python", "PostgreSQL", "REST API design", "Docker and Kubernetes"],
    },
    {
        "title": "Machine Learning Engineer",
        "department": "AI",
        "location": "San Francisco, CA",
        "description": "Ship LLM-powered features to production: retrieval pipelines, evaluation harnesses, "
        "and prompt tooling. Partner with product to turn prototypes into reliable systems.",
        "requirements": ["Python", "LLM applications", "Embeddings and vector search", "Model evaluation", "3+ years ML"],
    },
    {
        "title": "Product Designer",
        "department": "Design",
        "location": "New York, NY",
        "description": "Design the recruiter experience end to end, from research to polished UI in Figma. "
        "You will run usability studies and maintain our design system.",
        "requirements": ["Figma", "User research", "Design systems", "4+ years product design"],
    },
]

RESUMES = [
    """Priya Raman
Senior Software Engineer, 8 years building backend systems
priya.raman@example.com | Austin, TX
Experience: Staff-level Python and FastAPI services at a fintech handling 20k requests/sec.
Designed PostgreSQL schemas and led a migration to Kubernetes with Docker and Terraform on AWS.
Mentored four engineers and ran the API design review guild.
Skills: Python, FastAPI, PostgreSQL, Redis, Kafka, Docker, Kubernetes, AWS, REST API design""",
    """Marcus Chen
Machine Learning Engineer, 5 years
marcus.chen@example.com | San Francisco, CA
Built retrieval-augmented generation pipelines with embeddings and vector search (pgvector, FAISS).
Created an LLM evaluation harness used by 30 engineers. Shipped NLP models with PyTorch.
Skills: Python, PyTorch, LLM, NLP, Embeddings, Vector search, Model evaluation, SQL, Docker""",
    """Sofia Alvarez
Product Designer, 6 years
sofia.alvarez@example.com | Brooklyn, NY
Led end-to-end design for a B2B analytics product. Ran 40+ usability studies and user research
interviews. Built and maintained a Figma design system used across 5 product teams.
Skills: Figma, User research, Design systems, Prototyping, Accessibility""",
    """James Okafor
Full-Stack Developer, 3 years
james.okafor@example.com | Lagos, Nigeria (open to remote)
Built React and Node.js web apps; some Python scripting and MySQL. Deployed with Docker on Heroku.
Skills: JavaScript, TypeScript, React, Node.js, MySQL, Docker""",
    """Emily Novak
Data Scientist, 4 years
emily.novak@example.com | Chicago, IL
Built forecasting models in Python and scikit-learn; experimented with LLM classification and
prompt engineering. Strong SQL and Spark experience. Some model evaluation work.
Skills: Python, SQL, Spark, Machine Learning, LLM, Pandas""",
    """Daniel Kim
Backend Engineer, 6 years
daniel.kim@example.com | Seattle, WA
Go and Python microservices at an e-commerce company. Owned PostgreSQL performance tuning,
designed REST and gRPC APIs, and ran services on Kubernetes (EKS) with Docker.
Skills: Go, Python, PostgreSQL, Kubernetes, Docker, gRPC, REST API design, AWS""",
]


def seed() -> None:
    init_db()
    with SessionLocal() as db:
        if db.scalar(select(Job).limit(1)) is not None:
            print("Database already has data; skipping seed.")
            return
        for data in JOBS:
            job = Job(**data)
            job.embedding = embed_one(f"{job.title}\n{job.description}\n{' '.join(job.requirements)}")
            db.add(job)
        for text in RESUMES:
            p = parse_profile(text)
            c = Candidate(
                name=p.name, email=p.email, phone=p.phone, location=p.location, headline=p.headline,
                skills=p.skills, years_experience=p.years_experience, resume_text=text, resume_filename=None,
            )
            c.embedding = embed_one(f"{c.headline or ''}\nSkills: {', '.join(c.skills)}\n{text}")
            db.add(c)
        db.commit()
        print(f"Seeded {len(JOBS)} jobs and {len(RESUMES)} candidates.")


if __name__ == "__main__":
    seed()
