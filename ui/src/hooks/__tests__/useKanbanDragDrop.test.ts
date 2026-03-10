import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useKanbanDragDrop } from "../useKanbanDragDrop";

type Item = { id: string; status: "todo" | "doing" | "done" };

function createOptions(items: Item[]) {
  let current = items;
  return {
    items: current,
    setItems: ((fn: Item[] | ((prev: Item[]) => Item[])) => {
      current = typeof fn === "function" ? fn(current) : fn;
    }) as React.Dispatch<React.SetStateAction<Item[]>>,
    getId: (item: Item) => item.id,
    getColumn: (item: Item) => item.status,
    setColumn: (item: Item, col: "todo" | "doing" | "done"): Item => ({
      ...item,
      status: col,
    }),
  };
}

describe("useKanbanDragDrop", () => {
  it("initializes with draggedId=null and dragOverColumn=null", () => {
    const options = createOptions([{ id: "1", status: "todo" }]);
    const { result } = renderHook(() => useKanbanDragDrop(options));

    expect(result.current.draggedId).toBeNull();
    expect(result.current.dragOverColumn).toBeNull();
  });

  it("sets draggedId on handleDragStart", () => {
    const options = createOptions([{ id: "1", status: "todo" }]);
    const { result } = renderHook(() => useKanbanDragDrop(options));

    act(() => {
      const fakeEvent = {
        dataTransfer: {
          effectAllowed: "",
          setData: () => {},
        },
      } as unknown as React.DragEvent;
      result.current.handleDragStart(fakeEvent, "1");
    });

    expect(result.current.draggedId).toBe("1");
  });

  it("clears state on handleDragEnd", () => {
    const options = createOptions([{ id: "1", status: "todo" }]);
    const { result } = renderHook(() => useKanbanDragDrop(options));

    act(() => {
      const fakeEvent = {
        dataTransfer: {
          effectAllowed: "",
          setData: () => {},
        },
      } as unknown as React.DragEvent;
      result.current.handleDragStart(fakeEvent, "1");
    });

    expect(result.current.draggedId).toBe("1");

    act(() => {
      result.current.handleDragEnd();
    });

    expect(result.current.draggedId).toBeNull();
    expect(result.current.dragOverColumn).toBeNull();
  });
});
