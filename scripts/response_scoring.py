"""
Response Scoring System
=======================
Calculates relevance scores for agent responses based on message content,
context, mentions, and expertise matching.
"""

import re
from typing import Dict, List, Optional
from multi_agent_config import AgentProfile, get_agent_profile


def calculate_response_score(
    message_content: str,
    agent_name: str,
    bot_user_id: int,
    message_author_id: int,
    admin_user_id: int,
    is_bot_message: bool = False,
    mentioned_user_ids: Optional[List[int]] = None,
) -> float:
    """
    Calculate a relevance score (0.0 to 1.0) for whether an agent should respond.
    
    Args:
        message_content: The message text
        agent_name: Name of the agent (e.g., "architect")
        bot_user_id: Discord user ID of this bot
        message_author_id: Discord user ID of message author
        admin_user_id: Discord user ID of admin
        is_bot_message: Whether the message is from another bot
        mentioned_user_ids: List of mentioned user IDs in message
        
    Returns:
        Score from 0.0 (irrelevant) to 1.0 (highly relevant)
    """
    profile = get_agent_profile(agent_name)
    if not profile:
        return 0.0
    
    score = 0.0
    content_lower = message_content.lower()
    mentioned_user_ids = mentioned_user_ids or []

    # Direct @mention always wins — including raw <@id> if the mentions
    # cache is empty (common for bot-to-bot messages).
    mentioned_here = bot_user_id in mentioned_user_ids or (
        f"<@{bot_user_id}>" in message_content
        or f"<@!{bot_user_id}>" in message_content
    )
    if mentioned_here:
        return 1.0
    
    # Check if message is addressed to a DIFFERENT agent
    # If so, return 0.0 immediately (don't respond)
    other_agents = [
        "admiral", "admiral schubert", "schubert",
        "architect", "the architect",
        "quartermaster", "the quartermaster",
        "cartographer", "the cartographer",
        "dr_voss", "dr voss", "dr. voss", "voss",
        "proctor", "the proctor",
        "cortex", "dr. cortex", "dr cortex",
    ]
    # Remove this agent from the list so it can still respond to its own name
    agent_variants = {agent_name}
    if agent_name == "cortex":
        agent_variants = {"cortex", "dr. cortex", "dr cortex"}
    elif agent_name == "dr_voss":
        agent_variants = {"dr_voss", "dr voss", "dr. voss", "voss"}
    elif agent_name == "admiral":
        agent_variants = {"admiral", "admiral schubert", "schubert"}
    elif agent_name == "architect":
        agent_variants = {"architect", "the architect"}
    elif agent_name == "quartermaster":
        agent_variants = {"quartermaster", "the quartermaster"}
    elif agent_name == "cartographer":
        agent_variants = {"cartographer", "the cartographer"}
    elif agent_name == "proctor":
        agent_variants = {"proctor", "the proctor"}
    other_agents = [a for a in other_agents if a not in agent_variants]
    
    for other_agent in other_agents:
        # Check for patterns like "architect:" or "architect," at start of message
        if content_lower.startswith(f"{other_agent}:") or content_lower.startswith(f"{other_agent},"):
            return 0.0  # Message is for another agent, don't respond
    
    # Factor 1: Direct @mention (highest priority)
    if bot_user_id in mentioned_user_ids:
        score += 0.6
    
    # Factor 2: Name mention in text
    agent_patterns = [
        f"{agent_name}:",
        f"{agent_name},",
        f"hey {agent_name}",
        f"hi {agent_name}",
        f"@{agent_name}",
        f"{agent_name} can you",
        f"{agent_name} please",
    ]
    if any(pattern in content_lower for pattern in agent_patterns):
        score += 0.4
    
    # Factor 3: Delegation patterns (from coordinator)
    if is_bot_message:
        delegation_patterns = [
            f"{agent_name}, please",
            f"delegating to {agent_name}",
            f"handing off to {agent_name}",
            f"{agent_name}: handle",
            f"{agent_name} can handle",
        ]
        if any(pattern in content_lower for pattern in delegation_patterns):
            score += 0.5
    
    # Factor 4: Expertise keyword matching
    keyword_score = _calculate_keyword_score(content_lower, profile.expertise_keywords)
    score += keyword_score * 0.3  # Max 0.3 from keywords
    
    # Factor 5: Message from admin (boost for all agents)
    if message_author_id == admin_user_id and not is_bot_message:
        score += 0.1
    
    # Factor 6: Question indicators (boost for coordinator/admiral)
    if profile.role.value == "coordinator":
        question_patterns = ["what", "how", "why", "when", "where", "who", "?"]
        if any(pattern in content_lower for pattern in question_patterns):
            score += 0.1
    
    # Clamp score to 0.0-1.0 range
    return min(1.0, max(0.0, score))


def _calculate_keyword_score(content: str, keywords: List[str]) -> float:
    """
    Calculate keyword match score based on frequency and prominence.
    
    Returns:
        Score from 0.0 to 1.0
    """
    if not keywords:
        return 0.0
    
    # Count keyword matches
    matches = 0
    total_words = len(content.split())
    
    for keyword in keywords:
        # Use word boundary matching for better accuracy
        pattern = r'\b' + re.escape(keyword) + r'\b'
        matches += len(re.findall(pattern, content))
    
    if total_words == 0:
        return 0.0
    
    # Calculate density (matches per word)
    density = matches / max(total_words, 1)
    
    # Normalize to 0-1 range (cap at 0.5 density = score 1.0)
    score = min(1.0, density * 2.0)
    
    return score


def should_respond_immediately(score: float, agent_name: str) -> bool:
    """
    Determine if agent should respond immediately without waiting.
    
    Args:
        score: Response score from calculate_response_score
        agent_name: Name of the agent
        
    Returns:
        True if agent should respond immediately
    """
    profile = get_agent_profile(agent_name)
    if not profile:
        return False
    
    return score >= profile.urgent_threshold


def should_respond_with_delay(score: float, agent_name: str) -> bool:
    """
    Determine if agent should respond after a short delay.
    
    Args:
        score: Response score from calculate_response_score
        agent_name: Name of the agent
        
    Returns:
        True if agent should wait briefly before responding
    """
    profile = get_agent_profile(agent_name)
    if not profile:
        return False
    
    return profile.response_threshold <= score < profile.urgent_threshold


def get_response_delay(score: float, agent_name: str) -> float:
    """
    Get the recommended delay in seconds before responding.
    
    Args:
        score: Response score from calculate_response_score
        agent_name: Name of the agent
        
    Returns:
        Delay in seconds
    """
    profile = get_agent_profile(agent_name)
    if not profile:
        return 0.0
    
    if score >= profile.urgent_threshold:
        return 0.0  # Immediate
    elif score >= profile.response_threshold:
        return 2.0  # Brief delay to let coordinator respond first
    else:
        return float('inf')  # Don't respond
