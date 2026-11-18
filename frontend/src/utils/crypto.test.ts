import { describe, it, expect } from "vitest";
import { rfc8785CanonicalJson, verifyReceiptOffline } from "./crypto";

describe("RFC 8785 Canonical JSON Serialization", () => {
  it("sorts object keys lexicographically", () => {
    const input = { z: 1, a: 2, m: { b: 3, a: 4 } };
    const serialized = rfc8785CanonicalJson(input);
    expect(serialized).toBe('{"a":2,"m":{"a":4,"b":3},"z":1}');
  });

  it("handles arrays and nested elements cleanly without extra whitespace", () => {
    const input = { list: [3, 1, 2], name: "paylap" };
    const serialized = rfc8785CanonicalJson(input);
    expect(serialized).toBe('{"list":[3,1,2],"name":"paylap"}');
  });

  it("handles primitive values correctly", () => {
    expect(rfc8785CanonicalJson("hello")).toBe('"hello"');
    expect(rfc8785CanonicalJson(123)).toBe("123");
    expect(rfc8785CanonicalJson(true)).toBe("true");
    expect(rfc8785CanonicalJson(null)).toBe("null");
  });
});

describe("Offline Receipt Verification", () => {
  it("rejects empty or invalid receipt", async () => {
    const res = await verifyReceiptOffline(null);
    expect(res.valid).toBe(false);
  });

  it("rejects receipt missing signature or public key", async () => {
    const res = await verifyReceiptOffline({ contract_id: "ctr_123" });
    expect(res.valid).toBe(false);
    expect(res.error).toContain("missing 'signature'");
  });

  it("detects broken event sequence", async () => {
    const receipt = {
      contract_id: "ctr_test",
      signature: "c2lnbmF0dXJl",
      signer_public_key: "cHVibGlja2V5",
      events: [
        { seq: 1, type: "GENESIS" },
        { seq: 3, type: "OUT_OF_ORDER" },
      ],
    };
    const res = await verifyReceiptOffline(receipt);
    expect(res.valid).toBe(false);
    expect(res.error).toContain("Event sequence broken");
  });
});
