import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("evidence_review", Path(__file__).resolve().with_name("evidence_review.py"))
er = importlib.util.module_from_spec(spec)
spec.loader.exec_module(er)


class EvidenceReviewUnitTests(unittest.TestCase):
    def test_clean_json_text(self):
        self.assertEqual(er.clean_json_text('{"a": 1}'), '{"a": 1}')
        self.assertEqual(er.clean_json_text('```json\n{"a": 1}\n```'), '{"a": 1}')
        self.assertEqual(er.clean_json_text('Here is the json:\n```\n{"a": 1}\n```\nEnjoy!'), '{"a": 1}')
        self.assertEqual(er.clean_json_text('Some text {"a": 1} more text'), '{"a": 1}')

    def test_validators_accept_valid_payloads(self):
        s1 = {
            "answer_id": "ans-p1-v1",
            "participant": "p1",
            "version": 1,
            "summary": "Core summary",
            "claims": [{"claim_id": "c1", "statement": "Fact 1", "claim_type": "fact"}],
            "full_answer": "Complete text"
        }
        self.assertTrue(er.validate_stage1(s1)[0])

        s2 = {
            "review_id": "rev-1",
            "reviewer": "p2",
            "target_participant": "p1",
            "target_version": 1,
            "no_substantive_issues": False,
            "issues": [{
                "issue_id": "iss-1",
                "issue_type": "evidence_gap",
                "critique": "Missing citation",
                "proposed_check": "Check primary doc"
            }]
        }
        self.assertTrue(er.validate_stage2(s2)[0])

        s3 = {
            "revision_id": "rev-p1-v2",
            "participant": "p1",
            "version": 2,
            "issue_responses": [{
                "issue_id": "iss-1",
                "disposition": "accept",
                "reason": "Valid point"
            }],
            "revised_summary": "Updated summary",
            "revised_answer": "Updated full answer"
        }
        self.assertTrue(er.validate_stage3(s3)[0])

        s4 = {
            "synthesis_id": "syn-1",
            "usable_answer": "Final synthesized answer",
            "supported_points": ["Point A"],
            "unresolved_disagreements": ["Disagreement B"],
            "evidence_gaps": ["Gap C"],
            "next_checks": ["Check D"],
            "limitations": ["Limit E"],
            "stop_reason": "completed"
        }
        self.assertTrue(er.validate_stage4(s4)[0])

    def test_validators_reject_invalid_enums_and_missing_fields(self):
        # Stage 1: invalid claim_type
        bad_s1 = {
            "answer_id": "ans-1", "participant": "p1", "version": 1,
            "summary": "s", "claims": [{"claim_id": "c1", "statement": "s", "claim_type": "invalid_type"}],
            "full_answer": "text"
        }
        self.assertFalse(er.validate_stage1(bad_s1)[0])

        # Stage 2: missing critique
        bad_s2 = {
            "review_id": "rev-1", "reviewer": "p2", "target_participant": "p1",
            "target_version": 1, "no_substantive_issues": False,
            "issues": [{"issue_id": "iss-1", "issue_type": "evidence_gap", "proposed_check": "t"}]
        }
        self.assertFalse(er.validate_stage2(bad_s2)[0])

        # Stage 3: invalid disposition
        bad_s3 = {
            "revision_id": "rev-1", "participant": "p1", "version": 2,
            "issue_responses": [{"issue_id": "iss-1", "disposition": "disagree"}],
            "revised_summary": "s", "revised_answer": "a"
        }
        self.assertFalse(er.validate_stage3(bad_s3)[0])

        # Stage 4: missing usable_answer
        bad_s4 = {
            "synthesis_id": "syn-1",
            "supported_points": [], "unresolved_disagreements": [], "evidence_gaps": [],
            "next_checks": [], "limitations": [], "stop_reason": "completed"
        }
        self.assertFalse(er.validate_stage4(bad_s4)[0])

    def test_plan_review_assignments(self):
        # 2 participants
        p2 = er.plan_review_assignments(["p1", "p2"], 1)
        self.assertEqual(p2, [("p1", "p2"), ("p2", "p1")])

        # 3 participants
        p3_c1 = er.plan_review_assignments(["A", "B", "C"], 1)
        self.assertEqual(p3_c1, [("A", "B"), ("B", "C"), ("C", "A")])
        p3_c2 = er.plan_review_assignments(["A", "B", "C"], 2)
        self.assertEqual(p3_c2, [("A", "C"), ("B", "A"), ("C", "B")])

        # Ensure no self-reviews
        for cycle in (1, 2, 3):
            assignments = er.plan_review_assignments(["A", "B", "C", "D"], cycle)
            for rev, tgt in assignments:
                self.assertNotEqual(rev, tgt)

    def test_orchestrator_end_to_end_mock(self):
        def mock_call(provider, prompt, system_prompt):
            if "Candidate to Review" in prompt or "expert reviewer" in system_prompt:
                # Stage 2: Cross-review
                payload = {
                    "review_id": f"rev-{provider}",
                    "reviewer": provider,
                    "target_participant": "mock_target",
                    "target_version": 1,
                    "no_substantive_issues": False,
                    "issues": [{
                        "issue_id": "iss-1",
                        "issue_type": "logical_flaw",
                        "critique": "Overly optimistic bound",
                        "proposed_check": "Test with max input"
                    }]
                }
            elif "original author" in system_prompt or "Review Feedback Received" in prompt:
                # Stage 3: Revision
                payload = {
                    "revision_id": f"rev-{provider}-v2",
                    "participant": provider,
                    "version": 2,
                    "issue_responses": [{
                        "issue_id": "iss-1",
                        "disposition": "partly_accept",
                        "reason": "Clarified bounds"
                    }],
                    "revised_summary": f"Revised summary by {provider}",
                    "revised_answer": f"Revised detailed answer by {provider}"
                }
            elif "Lead Synthesizer" in system_prompt:
                # Stage 4: Synthesis
                payload = {
                    "synthesis_id": "syn-final",
                    "usable_answer": "Final synthesized answer",
                    "supported_points": ["Consensus on basic latency"],
                    "unresolved_disagreements": ["Disagreement on peak load limits"],
                    "evidence_gaps": ["Network partition behavior unmeasured"],
                    "next_checks": ["Run Jepsen test suite"],
                    "limitations": ["Assumes single datacenter"],
                    "stop_reason": "completed"
                }
            else:
                # Stage 1: Independent Answer
                payload = {
                    "answer_id": f"ans-{provider}-v1",
                    "participant": provider,
                    "version": 1,
                    "summary": f"Initial summary by {provider}",
                    "claims": [{
                        "claim_id": "c1",
                        "statement": "Algorithm terminates in O(n)",
                        "claim_type": "inference"
                    }],
                    "full_answer": f"Initial full answer by {provider}"
                }
            return {"status": "success", "response": json.dumps(payload)}

        orchestrator = er.EvidenceReviewOrchestrator(
            task="Evaluate Paxos vs Raft trade-offs",
            participants=["deepseek", "minimax", "glm"],
            call_fn=mock_call,
            cycles=1,
            synthesizer="glm"
        )
        trace = orchestrator.run()

        self.assertEqual(trace["schema_version"], er.SCHEMA_VERSION)
        self.assertEqual(len(trace["stage1_answers"]), 3)
        self.assertEqual(len(trace["cycles"]), 1)
        self.assertEqual(len(trace["cycles"][0]["assignments"]), 3)
        self.assertIn("synthesis", trace)
        self.assertEqual(trace["synthesis"]["stop_reason"], "completed")
        self.assertEqual(trace["synthesis"]["usable_answer"], "Final synthesized answer")
        self.assertEqual(trace["call_stats"]["failed_calls"], 0)

    def test_orchestrator_handles_format_repair(self):
        call_times = 0

        def mock_call_with_bad_first(provider, prompt, system_prompt):
            nonlocal call_times
            call_times += 1
            if call_times == 1:
                # Malformed JSON on first try
                return {"status": "success", "response": "Sorry, here is the result: {bad_json..."}
            # Repaired answer
            payload = {
                "answer_id": f"ans-{provider}-v1",
                "participant": provider,
                "version": 1,
                "summary": "Repaired summary",
                "claims": [{"claim_id": "c1", "statement": "s", "claim_type": "fact"}],
                "full_answer": "Repaired answer"
            }
            if "expert reviewer" in system_prompt:
                payload = {
                    "review_id": "rev-1", "reviewer": provider, "target_participant": "x",
                    "target_version": 1, "no_substantive_issues": True, "issues": []
                }
            elif "original author" in system_prompt:
                payload = {
                    "revision_id": "rev-v2", "participant": provider, "version": 2,
                    "issue_responses": [], "revised_summary": "s", "revised_answer": "a"
                }
            elif "Lead Synthesizer" in system_prompt:
                payload = {
                    "synthesis_id": "s", "usable_answer": "u", "supported_points": [],
                    "unresolved_disagreements": [], "evidence_gaps": [], "next_checks": [],
                    "limitations": [], "stop_reason": "completed"
                }
            return {"status": "success", "response": json.dumps(payload)}

        orchestrator = er.EvidenceReviewOrchestrator(
            task="Task",
            participants=["p1", "p2"],
            call_fn=mock_call_with_bad_first,
            cycles=1
        )
        trace = orchestrator.run()
        self.assertEqual(trace["call_stats"]["repairs"], 1)
        self.assertEqual(trace["stage1_answers"]["p1"]["summary"], "Repaired summary")

    def test_orchestrator_insufficient_candidates_stops_early(self):
        def mock_failing_calls(provider, prompt, system_prompt):
            if provider == "p1":
                return {"status": "success", "response": json.dumps({
                    "answer_id": "ans-p1-v1", "participant": "p1", "version": 1,
                    "summary": "s", "claims": [{"claim_id": "c1", "statement": "st", "claim_type": "fact"}],
                    "full_answer": "ans"
                })}
            return {"status": "failed", "error": "rate limit"}

        orchestrator = er.EvidenceReviewOrchestrator(
            task="Task",
            participants=["p1", "p2"],
            call_fn=mock_failing_calls,
            cycles=1
        )
        trace = orchestrator.run()
        self.assertEqual(trace["synthesis"]["stop_reason"], "stage1_insufficient_candidates")
        self.assertEqual(len(trace["cycles"]), 0)

    def test_orchestrator_budget_limit_stops_early(self):
        def mock_call(provider, prompt, system_prompt):
            payload = {
                "answer_id": f"ans-{provider}-v1", "participant": provider, "version": 1,
                "summary": "s", "claims": [{"claim_id": "c1", "statement": "st", "claim_type": "fact"}],
                "full_answer": "ans"
            }
            return {"status": "success", "response": json.dumps(payload)}

        # Setting max_calls=2 with 2 participants means Stage 1 consumes all calls
        orchestrator = er.EvidenceReviewOrchestrator(
            task="Task",
            participants=["p1", "p2"],
            call_fn=mock_call,
            cycles=1,
            max_calls=2
        )
        trace = orchestrator.run()
        # Stage 2 calls will fail with budget limit
        self.assertTrue(any(r.get("failed") for r in trace["cycles"][0]["reviews"].values()))

    def test_orchestrator_two_cycles(self):
        def mock_call(provider, prompt, system_prompt):
            if "expert reviewer" in system_prompt:
                payload = {
                    "review_id": f"rev-{provider}", "reviewer": provider, "target_participant": "t",
                    "target_version": 1, "no_substantive_issues": True, "issues": []
                }
            elif "original author" in system_prompt:
                payload = {
                    "revision_id": f"rev-{provider}-v", "participant": provider, "version": 2,
                    "issue_responses": [], "revised_summary": "revised", "revised_answer": "revised"
                }
            elif "Lead Synthesizer" in system_prompt:
                payload = {
                    "synthesis_id": "syn", "usable_answer": "done", "supported_points": [],
                    "unresolved_disagreements": [], "evidence_gaps": [], "next_checks": [],
                    "limitations": [], "stop_reason": "completed"
                }
            else:
                payload = {
                    "answer_id": f"ans-{provider}-v1", "participant": provider, "version": 1,
                    "summary": "s", "claims": [{"claim_id": "c1", "statement": "st", "claim_type": "fact"}],
                    "full_answer": "ans"
                }
            return {"status": "success", "response": json.dumps(payload)}

        orchestrator = er.EvidenceReviewOrchestrator(
            task="Task",
            participants=["A", "B", "C"],
            call_fn=mock_call,
            cycles=2
        )
        trace = orchestrator.run()
        self.assertEqual(len(trace["cycles"]), 2)
        # Verify assignments: Cycle 1 is A->B, B->C, C->A; Cycle 2 is A->C, B->A, C->B
        self.assertEqual(trace["cycles"][0]["assignments"], [("A", "B"), ("B", "C"), ("C", "A")])
        self.assertEqual(trace["cycles"][1]["assignments"], [("A", "C"), ("B", "A"), ("C", "B")])
        self.assertEqual(trace["synthesis"]["stop_reason"], "completed")


if __name__ == "__main__":
    unittest.main()
