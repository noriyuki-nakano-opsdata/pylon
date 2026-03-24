import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ProjectNew } from "../ProjectNew";

const navigateMock = vi.fn();
const createProjectMock = vi.fn();

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

vi.mock("@/contexts/TenantProjectContext", () => ({
  useTenantProject: () => ({
    currentTenant: { id: "default", name: "Default Org" },
    createProject: createProjectMock,
  }),
}));

function renderPage() {
  return render(
    <MemoryRouter>
      <ProjectNew />
    </MemoryRouter>,
  );
}

describe("ProjectNew", () => {
  beforeEach(() => {
    navigateMock.mockReset();
    createProjectMock.mockReset();
    createProjectMock.mockResolvedValue({ slug: "demo-project" });
  });

  it("submits the form when Enter is pressed in the name field", async () => {
    renderPage();

    const nameInput = screen.getByLabelText("プロジェクト名");
    fireEvent.change(nameInput, { target: { value: "Revenue Command Center" } });
    fireEvent.submit(nameInput.closest("form")!);

    await waitFor(() =>
      expect(createProjectMock).toHaveBeenCalledWith({
        name: "Revenue Command Center",
        brief: "",
        githubRepo: "",
      }),
    );
  });

  it("normalizes GitHub URLs before submission", async () => {
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: /補足情報を先に入力する/i }));
    fireEvent.change(screen.getByLabelText("プロジェクト名"), { target: { value: "Repo Input" } });
    fireEvent.change(screen.getByLabelText("GitHub リポジトリ"), {
      target: { value: "https://github.com/openai/openai-python.git" },
    });
    fireEvent.blur(screen.getByLabelText("GitHub リポジトリ"));
    fireEvent.click(screen.getByRole("button", { name: /プロジェクトを作成してリサーチを開始/i }));

    await waitFor(() =>
      expect(createProjectMock).toHaveBeenCalledWith({
        name: "Repo Input",
        brief: "",
        githubRepo: "openai/openai-python",
      }),
    );
  });

  it("blocks invalid GitHub repository values and exposes toggle state", async () => {
    renderPage();

    const toggle = screen.getByRole("button", { name: /補足情報を先に入力する/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    fireEvent.change(screen.getByLabelText("プロジェクト名"), { target: { value: "Invalid Repo" } });
    fireEvent.change(screen.getByLabelText("GitHub リポジトリ"), {
      target: { value: "not-a-valid-repo" },
    });
    fireEvent.blur(screen.getByLabelText("GitHub リポジトリ"));

    expect(
      screen.getByText("GitHub リポジトリは owner/repo 形式または GitHub URL を入力してください"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /プロジェクトを作成してリサーチを開始/i })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: /プロジェクトを作成してリサーチを開始/i }));
    await waitFor(() => expect(createProjectMock).not.toHaveBeenCalled());
  });

  it("submits registered company and product identity when provided", async () => {
    renderPage();

    fireEvent.change(screen.getByLabelText("プロジェクト名"), { target: { value: "Pylon" } });
    fireEvent.click(screen.getByRole("button", { name: /運営会社と自社プロダクトを登録する/i }));
    fireEvent.change(screen.getByLabelText("会社名"), { target: { value: "Pylon Labs" } });
    fireEvent.change(screen.getByLabelText("自社プロダクト名"), { target: { value: "Pylon" } });
    fireEvent.change(screen.getByLabelText("公式サイト"), { target: { value: "https://pylon.example.com" } });
    fireEvent.blur(screen.getByLabelText("公式サイト"));
    fireEvent.change(screen.getByLabelText("除外したい同名サービス"), {
      target: { value: "Basler pylon, AppMatch Pylon" },
    });
    fireEvent.click(screen.getByRole("button", { name: /プロジェクトを作成してリサーチを開始/i }));

    await waitFor(() =>
      expect(createProjectMock).toHaveBeenCalledWith({
        name: "Pylon",
        brief: "",
        githubRepo: "",
        productIdentity: {
          companyName: "Pylon Labs",
          productName: "Pylon",
          officialWebsite: "https://pylon.example.com",
          aliases: [],
          excludedEntityNames: ["Basler pylon", "AppMatch Pylon"],
        },
      }),
    );
  });
});
