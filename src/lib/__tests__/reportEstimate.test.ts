import { afterEach, describe, expect, it } from "vitest";

import { estimateReportSeconds, recordReportBuild, resetReportEstimate } from "../reportEstimate";

describe("reportEstimate", () => {
  afterEach(() => resetReportEstimate());

  it("scales the default rate by the verse count, with a floor", () => {
    expect(estimateReportSeconds(1533)).toBe(130);
    expect(estimateReportSeconds(10)).toBe(5);
    expect(estimateReportSeconds(null)).toBeGreaterThan(30);
  });

  it("learns the machine's rate from a finished build and keeps it", () => {
    recordReportBuild(1000, 50);
    expect(estimateReportSeconds(2000)).toBe(100);
    recordReportBuild(1000, 80);
    expect(estimateReportSeconds(1000)).toBe(70);
    expect(Number(localStorage.getItem("bridge.reportSecondsPerVerse"))).toBeCloseTo(0.07);
  });

  it("ignores a build with nothing to learn from", () => {
    recordReportBuild(0, 50);
    recordReportBuild(100, 0);
    expect(estimateReportSeconds(1533)).toBe(130);
  });
});
