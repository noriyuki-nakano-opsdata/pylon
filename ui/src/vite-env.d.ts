/// <reference types="vite/client" />

declare module "monaco-editor/esm/vs/editor/editor.api" {
  export * from "monaco-editor";
}

declare module "*?worker" {
  const WorkerFactory: {
    new (): Worker;
  };

  export default WorkerFactory;
}
