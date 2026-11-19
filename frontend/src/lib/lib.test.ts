import { describe, expect, it } from "vitest";
import { parseSseBlock } from "./api";
import { normalizeIndianMobile, validateName } from "./phone";

describe("phone", () => {
  it("normalises valid Indian mobiles", () => {
    expect(normalizeIndianMobile("98765 43210")).toBe("+919876543210");
    expect(normalizeIndianMobile("+91-98765-43210")).toBe("+919876543210");
    expect(normalizeIndianMobile("09876543210")).toBe("+919876543210");
    expect(normalizeIndianMobile("९८७६५४३२१०")).toBe("+919876543210");
  });
  it("rejects invalid numbers", () => {
    for (const bad of ["12345", "5876543210", "abcdefghij", "+14155550123", "98765432101234", ""]) expect(normalizeIndianMobile(bad)).toBeNull();
  });
  it("validates names", () => {
    expect(validateName("Asha Rao")).toBe("Asha Rao");
    expect(validateName("आशा राव")).toBe("आशा राव");
    expect(validateName("1")).toBeNull();
    expect(validateName("<script>")).toBeNull();
  });
});

describe("sse parser", () => {
  it("parses event and JSON data, including Hindi text", () => {
    expect(parseSseBlock('event: token\ndata: {"text":"नमस्ते"}')).toEqual({ event: "token", data: { text: "नमस्ते" } });
  });
  it("ignores malformed or empty blocks", () => {
    expect(parseSseBlock("event: token")).toBeNull();
    expect(parseSseBlock("event: token\ndata: {oops")).toBeNull();
  });
});
