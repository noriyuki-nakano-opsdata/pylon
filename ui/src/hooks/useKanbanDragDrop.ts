import { useState, useCallback, useRef } from "react";

interface UseKanbanDragDropOptions<T, S extends string> {
  items: T[];
  setItems: React.Dispatch<React.SetStateAction<T[]>>;
  getId: (item: T) => string;
  getColumn: (item: T) => S;
  setColumn: (item: T, column: S) => T;
  onMove?: (itemId: string, fromColumn: S, toColumn: S) => Promise<void>;
}

interface UseKanbanDragDropReturn<S extends string> {
  draggedId: string | null;
  dragOverColumn: S | null;
  handleDragStart: (e: React.DragEvent, itemId: string) => void;
  handleDragOver: (e: React.DragEvent, column: S) => void;
  handleDragLeave: () => void;
  handleDrop: (e: React.DragEvent, column: S) => void;
  handleDragEnd: () => void;
}

export function useKanbanDragDrop<T, S extends string>(
  options: UseKanbanDragDropOptions<T, S>,
): UseKanbanDragDropReturn<S> {
  const { items, setItems, getId, getColumn, setColumn, onMove } = options;

  const [draggedId, setDraggedId] = useState<string | null>(null);
  const [dragOverColumn, setDragOverColumn] = useState<S | null>(null);
  const snapshotRef = useRef<T[]>([]);

  const handleDragStart = useCallback(
    (e: React.DragEvent, itemId: string) => {
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", itemId);
      setDraggedId(itemId);
    },
    [],
  );

  const handleDragOver = useCallback(
    (e: React.DragEvent, column: S) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      setDragOverColumn(column);
    },
    [],
  );

  const handleDragLeave = useCallback(() => {
    setDragOverColumn(null);
  }, []);

  const handleDrop = useCallback(
    async (e: React.DragEvent, targetColumn: S) => {
      e.preventDefault();
      const itemId = e.dataTransfer.getData("text/plain");

      // Save snapshot for rollback
      snapshotRef.current = items;

      // Find dragged item and check if column changed
      const draggedItem = items.find((item) => getId(item) === itemId);
      if (!draggedItem || getColumn(draggedItem) === targetColumn) {
        setDraggedId(null);
        setDragOverColumn(null);
        return;
      }

      const fromColumn = getColumn(draggedItem);

      // Optimistic update
      setItems((prev) =>
        prev.map((item) =>
          getId(item) === itemId ? setColumn(item, targetColumn) : item,
        ),
      );
      setDraggedId(null);
      setDragOverColumn(null);

      // Persist via callback
      if (onMove) {
        try {
          await onMove(itemId, fromColumn, targetColumn);
        } catch {
          // Revert to snapshot on error
          setItems(snapshotRef.current);
        }
      }
    },
    [items, getId, getColumn, setColumn, setItems, onMove],
  );

  const handleDragEnd = useCallback(() => {
    setDraggedId(null);
    setDragOverColumn(null);
  }, []);

  return {
    draggedId,
    dragOverColumn,
    handleDragStart,
    handleDragOver,
    handleDragLeave,
    handleDrop,
    handleDragEnd,
  };
}
