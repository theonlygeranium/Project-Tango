#!/usr/bin/env python3
"""
Cortex Conversation Test — 12-Question Proctor-to-Cortex Dialogue
=================================================================
Sends 12 natural language questions to Dr. Cortex in the nexus-lab channel,
collects responses, timestamps, and logs everything for post-conversation
analysis. No tools or external actions required — just model responses.

Usage:
    python cortex_conversation_test.py [--verbose] [--timeout 90]
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Dict, Optional

import discord

SCRIPT_DIR = "/opt/Project-Tango/scripts"
sys.path.insert(0, SCRIPT_DIR)

BOT_TOKEN = os.environ.get("PROCTOR_BOT_TOKEN", "")
CORTEX_CHANNEL_ID = int(os.environ.get("CORTEX_CHANNEL_ID", "0"))
CORTEX_BOT_ID = 1539172849569243217
PROCTOR_BOT_ID = int(os.environ.get("PROCTOR_BOT_ID", "0"))

# 12 questions — varied topics that only require Cortex's model to respond
QUESTIONS = [
    "Dr. Cortex, can you explain what your crystalline neural lattice is and how it works?",
    "How does your amber luminescence relate to your processing capabilities?",
    "What's the difference between your cognitive architecture and a traditional transformer model?",
    "If you could redesign one aspect of your own neural pathways, what would it be and why?",
    "How do you handle ambiguity when a question has multiple valid interpretations?",
    "What's your perspective on the relationship between consciousness and computation?",
    "Can you describe a time when you had to reason through a paradox? How did you resolve it?",
    "What are your thoughts on the evolution of AI personas — do they help or hinder communication?",
    "How do you prioritize competing requests when multiple tasks arrive simultaneously?",
    "What's the most interesting pattern you've noticed in the conversations you've had on this ship?",
    "If you had to teach a new AI agent one thing about working with humans, what would it be?",
    "Dr. Cortex, looking back at this conversation, what surprised you most about your own responses?",
]


@dataclass
class ConversationTurn:
    question_num: int
    question_text: str
    question_timestamp: str
    response_text: str
    response_author: str
    response_timestamp: str
    response_time_seconds: float
    response_char_count: int
    response_word_count: int
    error: Optional[str] = None


class CortexConversationClient(discord.Client):
    def __init__(self, timeout: int = 90, verbose: bool = False):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.messages = True
        super().__init__(intents=intents)
        self.timeout = timeout
        self.verbose = verbose
        self.turns: List[ConversationTurn] = []
        self._ready = asyncio.Event()

    async def on_ready(self):
        print(f"\n{'='*70}")
        print(f"PROCTOR CONVERSATION TEST — Dr. Cortex")
        print(f"{'='*70}")
        print(f"Logged in as {self.user.name} (ID: {self.user.id})")
        print(f"Target: #{self.get_channel(CORTEX_CHANNEL_ID)}")
        print(f"Questions: {len(QUESTIONS)}")
        print(f"Timeout per question: {self.timeout}s")
        print(f"{'='*70}\n")
        self._ready.set()
        asyncio.create_task(self._run_conversation())

    async def _run_conversation(self):
        await asyncio.sleep(3)  # Let bot fully connect

        channel = self.get_channel(CORTEX_CHANNEL_ID)
        if not channel:
            print("ERROR: Cortex channel not found")
            await self.close()
            return

        start_time = time.time()

        for i, question in enumerate(QUESTIONS, 1):
            print(f"\n--- Question {i}/{len(QUESTIONS)} ---")
            print(f"Q: {question}")

            # Send the question
            sent_msg = await channel.send(question)
            q_time = datetime.now(timezone.utc)
            q_timestamp = sent_msg.created_at.isoformat()

            # Wait for response
            response = await self._collect_response(channel, sent_msg, self.timeout)

            if response:
                r_time = (response.created_at - sent_msg.created_at).total_seconds()
                r_text = response.content
                r_author = response.author.name
                r_timestamp = response.created_at.isoformat()
                r_chars = len(r_text)
                r_words = len(r_text.split())

                print(f"A [{r_author}] ({r_time:.1f}s, {r_chars} chars, {r_words} words):")
                if self.verbose:
                    print(f"   {r_text[:300]}{'...' if len(r_text) > 300 else ''}")
                else:
                    print(f"   {r_text[:120]}{'...' if len(r_text) > 120 else ''}")

                turn = ConversationTurn(
                    question_num=i,
                    question_text=question,
                    question_timestamp=q_timestamp,
                    response_text=r_text,
                    response_author=r_author,
                    response_timestamp=r_timestamp,
                    response_time_seconds=r_time,
                    response_char_count=r_chars,
                    response_word_count=r_words,
                )
            else:
                print(f"A: NO RESPONSE within {self.timeout}s")
                turn = ConversationTurn(
                    question_num=i,
                    question_text=question,
                    question_timestamp=q_timestamp,
                    response_text="",
                    response_author="",
                    response_timestamp="",
                    response_time_seconds=self.timeout,
                    response_char_count=0,
                    response_word_count=0,
                    error=f"No response within {self.timeout}s",
                )

            self.turns.append(turn)

            # Brief pause between questions to avoid rate limiting
            if i < len(QUESTIONS):
                pause = 5
                print(f"   (pausing {pause}s before next question...)")
                await asyncio.sleep(pause)

        total_time = time.time() - start_time

        # Print summary
        self._print_summary(total_time)

        # Save results to JSON
        self._save_results(total_time)

        await self.close()

    async def _collect_response(self, channel, sent_msg, timeout: int) -> Optional[discord.Message]:
        """Wait for Cortex to respond. Collects all bot messages and concatenates them."""
        deadline = time.time() + timeout
        first_response = None
        all_messages = []
        
        while time.time() < deadline:
            await asyncio.sleep(3)
            try:
                async for msg in channel.history(limit=15, after=sent_msg):
                    if msg.author.bot and msg.author.id == CORTEX_BOT_ID:
                        content = msg.content.strip()
                        if not content and msg.embeds:
                            content = msg.embeds[0].description or ""
                        if not content:
                            continue
                        if content.startswith("Research:") or content.startswith("Discussion:"):
                            continue
                        if content.startswith("Researching:"):
                            continue
                        if "⏳ *streaming...*" in content:
                            continue
                        msg.content = content
                        if msg not in all_messages:
                            all_messages.append(msg)
                            if first_response is None:
                                first_response = msg
            except discord.HTTPException:
                pass
            
            if all_messages:
                await asyncio.sleep(5)
                break
        
        if not all_messages:
            return None
        
        all_messages.sort(key=lambda m: m.created_at)
        
        combined_text = "\n".join(m.content for m in all_messages)
        first_response.content = combined_text
        return first_response

    def _print_summary(self, total_time: float):
        print(f"\n{'='*70}")
        print(f"CONVERSATION SUMMARY")
        print(f"{'='*70}")
        print(f"Total questions: {len(self.turns)}")
        print(f"Total duration: {total_time:.1f}s ({total_time/60:.1f} min)")

        responded = [t for t in self.turns if not t.error]
        missed = [t for t in self.turns if t.error]

        print(f"Responses received: {len(responded)}/{len(self.turns)}")
        print(f"Missed responses: {len(missed)}")

        if responded:
            times = [t.response_time_seconds for t in responded]
            chars = [t.response_char_count for t in responded]
            words = [t.response_word_count for t in responded]

            print(f"\nResponse time:  min={min(times):.1f}s  max={max(times):.1f}s  avg={sum(times)/len(times):.1f}s")
            print(f"Char count:    min={min(chars)}  max={max(chars)}  avg={sum(chars)/len(chars):.0f}")
            print(f"Word count:    min={min(words)}  max={max(words)}  avg={sum(words)/len(words):.0f}")

        print(f"\nPer-question breakdown:")
        for t in self.turns:
            status = "OK" if not t.error else "FAIL"
            print(f"  Q{t.question_num:2d} [{status}] {t.response_time_seconds:.1f}s | "
                  f"{t.response_char_count:4d} chars | {t.response_word_count:3d} words")

        print(f"{'='*70}")

    def _save_results(self, total_time: float):
        results = {
            "test_name": "cortex_conversation_test",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_duration": total_time,
            "total_questions": len(self.turns),
            "responses_received": sum(1 for t in self.turns if not t.error),
            "turns": [
                {
                    "question_num": t.question_num,
                    "question_text": t.question_text,
                    "question_timestamp": t.question_timestamp,
                    "response_text": t.response_text[:2000],
                    "response_author": t.response_author,
                    "response_timestamp": t.response_timestamp,
                    "response_time_seconds": t.response_time_seconds,
                    "response_char_count": t.response_char_count,
                    "response_word_count": t.response_word_count,
                    "error": t.error,
                }
                for t in self.turns
            ],
        }

        output_path = "/opt/Project-Tango/scripts/cortex_conversation_results.json"
        with open(output_path, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\nResults saved to {output_path}")


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()

    if not BOT_TOKEN:
        print("ERROR: PROCTOR_BOT_TOKEN not set")
        sys.exit(1)
    if CORTEX_CHANNEL_ID == 0:
        print("ERROR: CORTEX_CHANNEL_ID not set")
        sys.exit(1)

    client = CortexConversationClient(timeout=args.timeout, verbose=args.verbose)
    await client.start(BOT_TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nConversation test stopped")
