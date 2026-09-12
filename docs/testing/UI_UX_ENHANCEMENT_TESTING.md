# UI/UX Enhancement Testing Guide

## Pre-Deployment Verification

### Syntax & Import Checks
- [ ] All Python files compile without syntax errors
- [ ] All imports resolve correctly in bot venv
- [ ] No linter errors in modified files
- [ ] All new modules in correct location

### Code Review Checklist
- [ ] discord_ux_utils.py - Foundation module
- [ ] channel_onboarding.py - Onboarding system
- [ ] pinned_resources_tools.py - Pinned resource tools
- [ ] poll_tools.py - Poll creation tools
- [ ] Modified bot scripts (8 files)
- [ ] Modified UI components

## Feature Testing

### Feature 1: Silent Notifications
- Test: Trigger agent loop, verify progress updates don't push-notify
- Test: Verify final response DOES push-notify
- Expected: Badge-only for progress, full notification for results

### Feature 2: Native Typing Indicators
- Test: Send agent request, observe typing indicator within 1s
- Test: Verify typing persists >10 seconds
- Expected: "Bot is typing..." throughout processing

### Feature 3: Channel Onboarding
- Test: Restart bot, verify topic and 3 pinned embeds
- Test: Verify no push notifications during onboarding
- Expected: Silent channel setup

### Feature 4: Pinned Resources
- Test: Ask agent to pin/unpin/list resources
- Expected: Agent manages pins via natural language

### Feature 5: Native Polls
- Test: Create poll via agent
- Test: Verify native rendering and voting
- Expected: Working Discord poll

### Feature 6: Thread Isolation
- Test: Short request stays in main channel
- Test: Long request creates thread
- Expected: Complex tasks isolated

## Integration Scenarios

### Scenario 1: Complex Task with Thread
1. Send long multi-step request
2. Verify typing indicator in thread
3. Verify silent progress updates
4. Verify notifiable final response

### Scenario 2: Poll in Multi-Agent Channel
1. Create poll
2. Verify all bots see it
3. Verify voting works

## Production Readiness
- [ ] All tests pass
- [ ] Performance acceptable
- [ ] Error handling verified
- [ ] Rollback procedures documented
