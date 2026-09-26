"""The specialist agents. Each one is a focused Claude call with a typed output;
the orchestrator decides when each runs and persists the results."""

FAIRNESS = """Evaluate only job-relevant qualifications: skills, experience, and demonstrated results.
Never consider or infer age, gender, race, ethnicity, religion, nationality, disability,
marital or family status, or other protected characteristics, and do not penalize career gaps
without job-relevant evidence. Cite evidence from the provided material for every judgment."""


def job_brief(job) -> str:
    reqs = "\n".join(f"- {r}" for r in job.requirements) or "- (none listed)"
    return (
        f"<job>\nTitle: {job.title}\nDepartment: {job.department or '-'}\nLocation: {job.location or '-'}\n"
        f"Requirements:\n{reqs}\n\nDescription:\n{job.description}\n</job>"
    )


def _parsed_history(profile: dict) -> str:
    """Parsed work history and education, so agents don't have to re-derive dates from the resume."""
    out = []
    for job in profile.get("employment_history") or []:
        where = f" at {job['company']}" if job.get("company") else ""
        out.append(f"- {job.get('title')}{where} ({job.get('start') or '?'} to {job.get('end') or '?'})")
    for ed in profile.get("education") or []:
        parts = [ed.get("degree"), ed.get("field"), ed.get("institution"), ed.get("year")]
        out.append("- Education: " + ", ".join(p for p in parts if p))
    if profile.get("certifications"):
        out.append("- Certifications: " + "; ".join(profile["certifications"]))
    if profile.get("years_from_dates") is not None:
        out.append(f"- Experience from job dates: {profile['years_from_dates']} years")
    return "\n".join(out)


def candidate_brief(candidate) -> str:
    history = _parsed_history(candidate.profile or {})
    return (
        f"<candidate>\nName: {candidate.name}\nHeadline: {candidate.headline or '-'}\n"
        f"Location: {candidate.location or '-'}\nSkills: {', '.join(candidate.skills) or '-'}\n"
        f"Years of experience: {candidate.years_experience if candidate.years_experience is not None else '-'}\n"
        + (f"Parsed history:\n{history}\n" if history else "")
        + f"\nResume:\n{candidate.resume_text}\n</candidate>"
    )
