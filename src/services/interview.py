import logging
from datetime import datetime, timezone

from pydantic_ai.usage import Usage

from agents.interview_agent import interview_agent
from agents.resume_agent import resume_agent
from db.candidate_repository import get_candidate_by_id, update_candidate_by_id
from models.agent_dependencies import AgentDependencies
from models.session_state import SessionState, session_store
from tools.resume_parser import parse_resume_summary
from tools.vapi_client import start_vapi_call

logger = logging.getLogger(__name__)


def extract_first_name(full_name: str) -> str:
    """
    Extracts the first non-initial word from a full name string.
    Skips over initials like 'J.' or 'A.' and capitalizes the result.
    Assumes at least one valid word exists.
    """
    return next(
        part.capitalize()
        for part in full_name.strip().split()
        if len(part) > 1 and not part.endswith(".")
    )


async def run_interview(candidate_id: str):
    candidate = get_candidate_by_id(candidate_id)
    first_name = extract_first_name(candidate.profile.name)
    resume_agent_usage = Usage()
    resume_url = candidate.profile.resume_url
    
    if resume_url:
        logger.info(
            f"Resume available for candidate {candidate_id}. Kicking off Resume Agent."
        )
        agent_deps = AgentDependencies(candidate=candidate)

        resume_agent_message = "analyze the resume for the candidate"
        resume_agent_response = await resume_agent.run(
            resume_agent_message, deps=agent_deps, usage=resume_agent_usage
        )
        logger.info(f"Resume Summary output from LLM {resume_agent_response.output}")

        resume_summary = parse_resume_summary(resume_agent_response.output)
        logger.info(f"Resume summary: {resume_summary}")

        candidate.resume_summary = resume_summary
        candidate.status = "RESUME_SUMMARY_GENERATED"
        update_candidate_by_id(candidate=candidate)
    else:
        logger.info(
            f"Resume not available for candidate {candidate_id}. Kicking off Interview."
        )

    call_response = await start_vapi_call(
        candidate_id=candidate.profile.candidate_id,
        phone_number=candidate.profile.phone,
        greeting=f"Hello.. am I speaking with {first_name}?",
    )

    call_id = call_response["id"]
    control_url = call_response["monitor"]["controlUrl"]

    deps = AgentDependencies(candidate=candidate)

    session_store[call_id] = SessionState(
        agent=interview_agent,
        agent_dependencies=deps,
        resume_agent_usage=resume_agent_usage,
        interview_agent_usage=Usage(),
        evaluation_agent_usage=Usage(),
        message_history=[],
        start_time=datetime.now(timezone.utc),
        control_url=control_url,
    )

    logger.info(f"Started new session with session_id: {call_id}")

    return {"status": "call_started", "vapi_response": call_response}
