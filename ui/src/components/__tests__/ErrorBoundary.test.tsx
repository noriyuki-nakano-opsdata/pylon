import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ErrorBoundary } from "@/components/ErrorBoundary";

function Bomb({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) {
    throw new Error("boom");
  }
  return <div>safe</div>;
}

describe("ErrorBoundary", () => {
  it("resets when the reset key changes", () => {
    const { rerender } = render(
      <ErrorBoundary resetKey="/first">
        <Bomb shouldThrow />
      </ErrorBoundary>,
    );

    expect(screen.getByText("予期しないエラーが発生しました")).toBeInTheDocument();
    expect(screen.getByText("boom")).toBeInTheDocument();

    rerender(
      <ErrorBoundary resetKey="/second">
        <Bomb shouldThrow={false} />
      </ErrorBoundary>,
    );

    expect(screen.getByText("safe")).toBeInTheDocument();
  });
});
