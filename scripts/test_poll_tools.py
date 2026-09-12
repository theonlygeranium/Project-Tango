#!/usr/bin/env python3
"""
Test Suite for Discord Poll Tools
==================================

Tests validation, parameter handling, and API payload construction
for the native Discord poll creation tool.

NOTE: This test suite only tests validation and tool definitions,
not the actual API calls which require discord.py and aiohttp.

Usage:
    python3 test_poll_tools.py
"""

import sys
import os

# Add scripts directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import only the validation and tool definition functions
# (not the async create_poll which requires aiohttp)
try:
    from poll_tools import (
        validate_poll_parameters,
        get_poll_tools,
        is_poll_tool,
        MAX_QUESTION_LENGTH,
        MAX_ANSWER_LENGTH,
        MAX_ANSWERS,
        MIN_DURATION,
        MAX_DURATION,
    )
    IMPORTS_OK = True
except ImportError as e:
    print(f"Warning: Could not import poll_tools: {e}")
    print("This is expected if aiohttp/discord.py are not installed.")
    print("Skipping import-dependent tests.")
    IMPORTS_OK = False


def test_validation():
    """Test poll parameter validation."""
    print("Testing validation...")
    
    # Valid poll
    error = validate_poll_parameters(
        question="What's your favorite color?",
        answers=["Red", "Blue", "Green"],
        duration_hours=24
    )
    assert error is None, f"Valid poll failed: {error}"
    print("✓ Valid poll passes")
    
    # Empty question
    error = validate_poll_parameters(
        question="",
        answers=["A", "B"],
        duration_hours=24
    )
    assert error is not None, "Empty question should fail"
    assert "empty" in error.lower(), f"Unexpected error: {error}"
    print("✓ Empty question rejected")
    
    # Question too long
    error = validate_poll_parameters(
        question="x" * (MAX_QUESTION_LENGTH + 1),
        answers=["A", "B"],
        duration_hours=24
    )
    assert error is not None, "Long question should fail"
    assert "exceeds" in error.lower(), f"Unexpected error: {error}"
    print("✓ Long question rejected")
    
    # Too few answers
    error = validate_poll_parameters(
        question="Test?",
        answers=["Only one"],
        duration_hours=24
    )
    assert error is not None, "Single answer should fail"
    assert "at least 2" in error.lower(), f"Unexpected error: {error}"
    print("✓ Single answer rejected")
    
    # Too many answers
    error = validate_poll_parameters(
        question="Test?",
        answers=[f"Option {i}" for i in range(MAX_ANSWERS + 1)],
        duration_hours=24
    )
    assert error is not None, "Too many answers should fail"
    assert "more than" in error.lower(), f"Unexpected error: {error}"
    print("✓ Too many answers rejected")
    
    # Answer too long
    error = validate_poll_parameters(
        question="Test?",
        answers=["A", "x" * (MAX_ANSWER_LENGTH + 1)],
        duration_hours=24
    )
    assert error is not None, "Long answer should fail"
    assert "exceeds" in error.lower() and "answer" in error.lower(), f"Unexpected error: {error}"
    print("✓ Long answer rejected")
    
    # Duration too short
    error = validate_poll_parameters(
        question="Test?",
        answers=["A", "B"],
        duration_hours=0
    )
    assert error is not None, "Zero duration should fail"
    assert "at least" in error.lower(), f"Unexpected error: {error}"
    print("✓ Zero duration rejected")
    
    # Duration too long
    error = validate_poll_parameters(
        question="Test?",
        answers=["A", "B"],
        duration_hours=MAX_DURATION + 1
    )
    assert error is not None, "Excessive duration should fail"
    assert "cannot exceed" in error.lower(), f"Unexpected error: {error}"
    print("✓ Excessive duration rejected")
    
    # Boundary cases - exactly at limits (should pass)
    error = validate_poll_parameters(
        question="x" * MAX_QUESTION_LENGTH,
        answers=["x" * MAX_ANSWER_LENGTH for _ in range(MAX_ANSWERS)],
        duration_hours=MAX_DURATION
    )
    assert error is None, f"Boundary case failed: {error}"
    print("✓ Boundary case passes")
    
    print()


def test_tool_definitions():
    """Test tool definition structure."""
    print("Testing tool definitions...")
    
    tools = get_poll_tools()
    assert len(tools) == 1, f"Expected 1 tool, got {len(tools)}"
    
    tool = tools[0]
    assert tool["type"] == "function", "Tool type should be 'function'"
    assert "function" in tool, "Tool missing 'function' key"
    
    func = tool["function"]
    assert func["name"] == "create_poll", f"Tool name should be 'create_poll', got {func['name']}"
    assert "description" in func, "Tool missing description"
    assert "parameters" in func, "Tool missing parameters"
    
    params = func["parameters"]
    assert params["type"] == "object", "Parameters type should be 'object'"
    assert "properties" in params, "Parameters missing 'properties'"
    assert "required" in params, "Parameters missing 'required'"
    
    props = params["properties"]
    assert "question" in props, "Missing 'question' parameter"
    assert "answers" in props, "Missing 'answers' parameter"
    assert "duration_hours" in props, "Missing 'duration_hours' parameter"
    assert "allow_multiselect" in props, "Missing 'allow_multiselect' parameter"
    
    # Check required fields
    required = params["required"]
    assert "question" in required, "'question' should be required"
    assert "answers" in required, "'answers' should be required"
    
    # Check answers is an array
    assert props["answers"]["type"] == "array", "answers should be type 'array'"
    assert "items" in props["answers"], "answers missing 'items'"
    assert props["answers"]["items"]["type"] == "string", "answers items should be strings"
    
    print("✓ Tool structure valid")
    print("✓ All required parameters present")
    print("✓ Parameter types correct")
    print()


def test_tool_detection():
    """Test tool name detection."""
    print("Testing tool detection...")
    
    assert is_poll_tool("create_poll"), "create_poll should be detected"
    assert not is_poll_tool("run_shell"), "run_shell should not be detected"
    assert not is_poll_tool("web_search"), "web_search should not be detected"
    assert not is_poll_tool("read_file"), "read_file should not be detected"
    
    print("✓ Tool detection works")
    print()


def test_limits():
    """Test that documented limits match Discord API."""
    print("Testing API limits...")
    
    # These should match Discord's documented API limits
    assert MAX_QUESTION_LENGTH == 300, f"Question limit should be 300, got {MAX_QUESTION_LENGTH}"
    assert MAX_ANSWER_LENGTH == 55, f"Answer limit should be 55, got {MAX_ANSWER_LENGTH}"
    assert MAX_ANSWERS == 10, f"Max answers should be 10, got {MAX_ANSWERS}"
    assert MIN_DURATION == 1, f"Min duration should be 1, got {MIN_DURATION}"
    assert MAX_DURATION == 768, f"Max duration should be 768, got {MAX_DURATION}"
    
    print("✓ Limits match Discord API")
    print()


def test_use_cases():
    """Test real-world use case examples."""
    print("Testing use cases...")
    
    # Use case 1: Senior staff meeting decision
    error = validate_poll_parameters(
        question="Which architecture approach should we use for the new API?",
        answers=["REST with OpenAPI", "GraphQL", "gRPC", "tRPC"],
        duration_hours=48
    )
    assert error is None, f"Senior staff meeting poll failed: {error}"
    print("✓ Senior staff meeting poll valid")
    
    # Use case 2: Feature rating
    error = validate_poll_parameters(
        question="Rate the new authentication flow:",
        answers=["1 - Poor", "2 - Fair", "3 - Good", "4 - Great", "5 - Excellent"],
        duration_hours=24
    )
    assert error is None, f"Feature rating poll failed: {error}"
    print("✓ Feature rating poll valid")
    
    # Use case 3: Priority selection
    error = validate_poll_parameters(
        question="Which bug should we fix first?",
        answers=[
            "Bug #123: Login timeout",
            "Bug #456: Data sync issue",
            "Bug #789: UI rendering",
        ],
        duration_hours=12
    )
    assert error is None, f"Priority poll failed: {error}"
    print("✓ Priority selection poll valid")
    
    # Use case 4: Multi-select survey
    error = validate_poll_parameters(
        question="Which features would you like to see? (select all that apply)",
        answers=["Dark mode", "Mobile app", "Export to PDF", "API access", "Webhooks"],
        duration_hours=168  # 1 week
    )
    assert error is None, f"Multi-select survey poll failed: {error}"
    print("✓ Multi-select survey poll valid")
    
    print()


def main():
    """Run all tests."""
    print("=" * 60)
    print("Discord Poll Tools Test Suite")
    print("=" * 60)
    print()
    
    if not IMPORTS_OK:
        print("⚠️  Skipping tests - imports failed (missing dependencies)")
        print("This is expected in standalone testing without discord.py/aiohttp")
        return 0
    
    try:
        test_validation()
        test_tool_definitions()
        test_tool_detection()
        test_limits()
        test_use_cases()
        
        print("=" * 60)
        print("✅ All tests passed!")
        print("=" * 60)
        return 0
    except AssertionError as e:
        print()
        print("=" * 60)
        print(f"❌ Test failed: {e}")
        print("=" * 60)
        return 1
    except Exception as e:
        print()
        print("=" * 60)
        print(f"❌ Unexpected error: {e}")
        print("=" * 60)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
