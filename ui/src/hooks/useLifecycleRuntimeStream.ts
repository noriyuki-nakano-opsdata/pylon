import { useEffect, useRef, useState } from "react";
import {
  lifecycleApi,
  type LifecyclePhaseTerminalEvent,
  type LifecycleRuntimeStreamPayload,
} from "@/api/lifecycle";
import type { LifecyclePhase, WorkflowRunLiveTelemetry } from "@/types/lifecycle";

const RECONNECT_DELAY_MS = 1000;
export type LifecycleRuntimeConnectionState = "inactive" | "connecting" | "live" | "reconnecting";

export function useLifecycleRuntimeStream(
  projectSlug: string,
  phase: LifecyclePhase | null,
  enabled: boolean,
) {
  const [runtime, setRuntime] = useState<LifecycleRuntimeStreamPayload | null>(null);
  const [liveTelemetry, setLiveTelemetry] = useState<WorkflowRunLiveTelemetry | null>(null);
  const [terminalEvent, setTerminalEvent] = useState<LifecyclePhaseTerminalEvent | null>(null);
  const [connectionState, setConnectionState] = useState<LifecycleRuntimeConnectionState>("inactive");
  const terminalKeyRef = useRef<string | null>(null);
  const hasConnectedRef = useRef(false);

  useEffect(() => {
    setRuntime(null);
    setLiveTelemetry(null);
    setTerminalEvent(null);
    setConnectionState(enabled ? "connecting" : "inactive");
    terminalKeyRef.current = null;
    hasConnectedRef.current = false;
  }, [projectSlug, phase, enabled]);

  useEffect(() => {
    if (!enabled || !projectSlug || !phase) return;
    let active = true;
    let reconnectTimer: number | null = null;
    let controller: AbortController | null = null;
    let terminalReached = false;

    const connect = async () => {
      while (active) {
        controller = new AbortController();
        setConnectionState(hasConnectedRef.current ? "reconnecting" : "connecting");
        try {
          await lifecycleApi.streamProjectEvents(projectSlug, phase, {
            signal: controller.signal,
            onEvent: ({ event, data }) => {
              if (!data) return;
              hasConnectedRef.current = true;
              setConnectionState("live");
              if (event === "project-runtime") {
                setRuntime(JSON.parse(data) as LifecycleRuntimeStreamPayload);
                return;
              }
              if (event === "run-live") {
                setLiveTelemetry(JSON.parse(data) as WorkflowRunLiveTelemetry | null);
                return;
              }
              if (event === "phase-terminal") {
                const payload = JSON.parse(data) as LifecyclePhaseTerminalEvent;
                const key = `${payload.phase}:${payload.runId}:${payload.status}`;
                if (terminalKeyRef.current !== key) {
                  terminalKeyRef.current = key;
                  setTerminalEvent(payload);
                }
                terminalReached = true;
              }
            },
          });
        } catch (error) {
          if (!active || controller.signal.aborted) break;
          console.debug("Lifecycle runtime stream disconnected", error);
        }
        if (!active || terminalReached) break;
        await new Promise<void>((resolve) => {
          reconnectTimer = window.setTimeout(() => resolve(), RECONNECT_DELAY_MS);
        });
      }
    };

    void connect();
    return () => {
      active = false;
      controller?.abort();
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
      }
    };
  }, [enabled, phase, projectSlug]);

  return {
    runtime,
    liveTelemetry,
    terminalEvent,
    connectionState,
  };
}
