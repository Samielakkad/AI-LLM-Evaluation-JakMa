import json
import unittest

import httpx

from scripts.response_parser import ResponseParseError, parse_endpoint_response
from scripts.run_eval import call_endpoint


class ParseEndpointResponseTests(unittest.TestCase):
    def test_parses_plain_text_worker_marker(self):
        parsed = parse_endpoint_response(
            "سلام من يوسف\n<<WORKERS:worker-1,worker-2>>", "text/plain"
        )

        self.assertEqual(parsed.response_text, "سلام من يوسف")
        self.assertEqual(parsed.cited_ids, ["worker-1", "worker-2"])
        self.assertEqual(parsed.pass1_result, {})

    def test_accepts_explicit_empty_worker_declarations(self):
        plain = parse_endpoint_response("clarify\n<<WORKERS:>>", "text/plain")
        structured = parse_endpoint_response(
            json.dumps({"message_darija": "clarify", "workers_to_show": []}),
            "application/json",
        )

        self.assertEqual(plain.cited_ids, [])
        self.assertEqual(structured.cited_ids, [])

    def test_parses_documented_json_response(self):
        payload = {
            "classification": {
                "trades": ["plumber"],
                "city": {"name": "Tangier", "confidence": 0.91},
            },
            "workers_to_show": [
                {"worker_id": "worker-1", "highlight_reason": "nearby"}
            ],
            "message_darija": "كاين يوسف",
        }

        parsed = parse_endpoint_response(
            json.dumps(payload), "application/json; charset=utf-8"
        )

        self.assertEqual(parsed.response_text, "كاين يوسف")
        self.assertEqual(parsed.cited_ids, ["worker-1"])
        self.assertEqual(parsed.pass1_result, payload["classification"])

    def test_preserves_nested_pass1_from_json_envelope(self):
        payload = {
            "data": {
                "response_text": "answer\n<<WORKERS:worker-1>>",
                "pass1": {
                    "trade": {"primary": "plumber", "secondary": []},
                    "city": {"name": "Tangier", "zone": {"id": "medina"}},
                },
            }
        }

        parsed = parse_endpoint_response(json.dumps(payload), "application/json")

        self.assertEqual(parsed.cited_ids, ["worker-1"])
        self.assertEqual(parsed.pass1_result["city"]["zone"]["id"], "medina")

    def test_parses_sse_tokens_openai_delta_and_nested_pass1(self):
        body = "\n".join(
            [
                "event: pass1",
                'data: {"pass1":{"trade":{"primary":"plumber"}}}',
                "",
                'data: {"token":"سلام "}',
                "",
                'data: {"choices":[{"delta":{"content":"عليكم"}}]}',
                "",
                'data: {"token":"\\n<<WORKERS:worker-1>>"}',
                "",
                "data: [DONE]",
                "",
            ]
        )

        parsed = parse_endpoint_response(body, "text/event-stream")

        self.assertEqual(parsed.response_text, "سلام عليكم")
        self.assertEqual(parsed.cited_ids, ["worker-1"])
        self.assertEqual(parsed.pass1_result["trade"]["primary"], "plumber")

    def test_prefers_complete_sse_message_and_structured_ids(self):
        body = "\n".join(
            [
                'data: {"token":"partial"}',
                "",
                "data: "
                + json.dumps(
                    {
                        "message_darija": "complete response",
                        "workers_to_show": [{"worker_id": "worker-1"}],
                        "classification": {"city": "Tangier"},
                    }
                ),
                "",
            ]
        )

        parsed = parse_endpoint_response(body, "text/event-stream")

        self.assertEqual(parsed.response_text, "complete response")
        self.assertEqual(parsed.cited_ids, ["worker-1"])
        self.assertEqual(parsed.pass1_result, {"city": "Tangier"})

    def test_rejects_conflicting_marker_and_structured_ids(self):
        payload = {
            "message_darija": "answer\n<<WORKERS:worker-1>>",
            "workers_to_show": [{"worker_id": "worker-2"}],
        }

        with self.assertRaisesRegex(ResponseParseError, "does not match"):
            parse_endpoint_response(json.dumps(payload), "application/json")

    def test_rejects_malformed_json_response(self):
        with self.assertRaisesRegex(ResponseParseError, "not valid JSON"):
            parse_endpoint_response("{not-json", "application/json")

    def test_rejects_content_after_worker_marker(self):
        with self.assertRaisesRegex(ResponseParseError, "must be the final"):
            parse_endpoint_response(
                "answer <<WORKERS:worker-1>> hidden tail", "text/plain"
            )

    def test_rejects_response_without_worker_declaration(self):
        with self.assertRaisesRegex(ResponseParseError, "does not declare"):
            parse_endpoint_response("unmarked answer", "text/plain")

    def test_rejects_empty_response_text_in_every_transport(self):
        responses = (
            ("<<WORKERS:worker-1>>", "text/plain"),
            (
                json.dumps(
                    {"message_darija": " ", "workers_to_show": ["worker-1"]}
                ),
                "application/json",
            ),
            (
                'data: {"message_darija":"","workers_to_show":["worker-1"]}\n\n',
                "text/event-stream",
            ),
        )
        for body, content_type in responses:
            with self.subTest(content_type=content_type):
                with self.assertRaisesRegex(ResponseParseError, "must not be empty"):
                    parse_endpoint_response(body, content_type)


class CallEndpointTests(unittest.TestCase):
    def test_uses_response_content_type_and_returns_parsed_contract(self):
        def handle(request):
            self.assertEqual(request.method, "POST")
            self.assertEqual(
                json.loads(request.content),
                {"query": "need a plumber", "conversation_id": "conversation-1"},
            )
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={
                    "message_darija": "كاين يوسف",
                    "workers_to_show": [{"worker_id": "worker-1"}],
                    "classification": {"trade": {"primary": "plumber"}},
                },
            )

        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            response_text, cited_ids, pass1, duration_ms = call_endpoint(
                "https://example.test/chat",
                "need a plumber",
                conversation_id="conversation-1",
                client=client,
            )

        self.assertEqual(response_text, "كاين يوسف")
        self.assertEqual(cited_ids, ["worker-1"])
        self.assertEqual(pass1["trade"]["primary"], "plumber")
        self.assertGreaterEqual(duration_ms, 0)


if __name__ == "__main__":
    unittest.main()
