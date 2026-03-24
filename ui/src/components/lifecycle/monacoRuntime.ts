import * as monaco from "monaco-editor/esm/vs/editor/editor.api";
import editorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";
import jsonWorker from "monaco-editor/esm/vs/language/json/json.worker?worker";
import cssWorker from "monaco-editor/esm/vs/language/css/css.worker?worker";
import htmlWorker from "monaco-editor/esm/vs/language/html/html.worker?worker";
import tsWorker from "monaco-editor/esm/vs/language/typescript/ts.worker?worker";
import "monaco-editor/esm/vs/language/json/monaco.contribution";
import "monaco-editor/esm/vs/language/css/monaco.contribution";
import "monaco-editor/esm/vs/language/html/monaco.contribution";
import "monaco-editor/esm/vs/language/typescript/monaco.contribution";
import "monaco-editor/min/vs/editor/editor.main.css";

let configured = false;

type MonacoTypeScriptApi = {
  typescriptDefaults: {
    setDiagnosticsOptions: (options: { noSemanticValidation: boolean; noSyntaxValidation: boolean }) => void;
    setCompilerOptions: (options: {
      allowJs: boolean;
      allowNonTsExtensions: boolean;
      jsx: number;
      target: number;
      module: number;
      moduleResolution: number;
    }) => void;
  };
  javascriptDefaults: {
    setDiagnosticsOptions: (options: { noSemanticValidation: boolean; noSyntaxValidation: boolean }) => void;
    setCompilerOptions: (options: {
      allowJs: boolean;
      allowNonTsExtensions: boolean;
      jsx: number;
      target: number;
      module: number;
      moduleResolution: number;
    }) => void;
  };
  JsxEmit: { ReactJSX: number };
  ScriptTarget: { ES2022: number };
  ModuleKind: { ESNext: number };
  ModuleResolutionKind: { NodeJs: number };
};

function ensureMonacoEnvironment() {
  const target = self as typeof self & {
    MonacoEnvironment?: {
      getWorker: (_moduleId: string, label: string) => Worker;
    };
  };

  if (target.MonacoEnvironment) return;

  target.MonacoEnvironment = {
    getWorker(_moduleId: string, label: string) {
      if (label === "json") return new jsonWorker();
      if (label === "css" || label === "scss" || label === "less") return new cssWorker();
      if (label === "html" || label === "handlebars" || label === "razor") return new htmlWorker();
      if (label === "typescript" || label === "javascript") return new tsWorker();
      return new editorWorker();
    },
  };
}

function configureMonaco() {
  if (configured) return;

  ensureMonacoEnvironment();

  const tsApi = (monaco.languages as unknown as { typescript: MonacoTypeScriptApi }).typescript;

  tsApi.typescriptDefaults.setDiagnosticsOptions({
    noSemanticValidation: true,
    noSyntaxValidation: true,
  });
  tsApi.javascriptDefaults.setDiagnosticsOptions({
    noSemanticValidation: true,
    noSyntaxValidation: true,
  });
  tsApi.typescriptDefaults.setCompilerOptions({
    allowJs: true,
    allowNonTsExtensions: true,
    jsx: tsApi.JsxEmit.ReactJSX,
    target: tsApi.ScriptTarget.ES2022,
    module: tsApi.ModuleKind.ESNext,
    moduleResolution: tsApi.ModuleResolutionKind.NodeJs,
  });
  tsApi.javascriptDefaults.setCompilerOptions({
    allowJs: true,
    allowNonTsExtensions: true,
    jsx: tsApi.JsxEmit.ReactJSX,
    target: tsApi.ScriptTarget.ES2022,
    module: tsApi.ModuleKind.ESNext,
    moduleResolution: tsApi.ModuleResolutionKind.NodeJs,
  });

  monaco.editor.defineTheme("pylon-ide", {
    base: "vs-dark",
    inherit: true,
    rules: [
      { token: "comment", foreground: "6B7280", fontStyle: "italic" },
      { token: "keyword", foreground: "F472B6" },
      { token: "string", foreground: "86EFAC" },
      { token: "number", foreground: "FBBF24" },
      { token: "delimiter", foreground: "CBD5E1" },
      { token: "type.identifier", foreground: "7DD3FC" },
      { token: "identifier", foreground: "E2E8F0" },
    ],
    colors: {
      "editor.background": "#0A0F16",
      "editor.foreground": "#E2E8F0",
      "editor.lineHighlightBackground": "#111827",
      "editor.lineHighlightBorder": "#00000000",
      "editorGutter.background": "#0D131D",
      "editorLineNumber.foreground": "#475569",
      "editorLineNumber.activeForeground": "#94A3B8",
      "editor.selectionBackground": "#1D4ED833",
      "editor.inactiveSelectionBackground": "#1E293B66",
      "editorCursor.foreground": "#7DD3FC",
      "editorIndentGuide.background1": "#1E293B",
      "editorIndentGuide.activeBackground1": "#334155",
      "editorWhitespace.foreground": "#1E293B",
      "editorBracketMatch.background": "#38BDF81A",
      "editorBracketMatch.border": "#38BDF833",
      "editorWidget.background": "#0F172A",
      "editorWidget.border": "#1E293B",
      "editorOverviewRuler.border": "#00000000",
      "editorStickyScroll.background": "#0F151E",
      "minimap.background": "#0A0F16",
      "scrollbarSlider.background": "#47556955",
      "scrollbarSlider.hoverBackground": "#64748B77",
      "scrollbarSlider.activeBackground": "#94A3B888",
    },
  });

  configured = true;
}

export async function loadMonaco() {
  configureMonaco();
  return monaco;
}
