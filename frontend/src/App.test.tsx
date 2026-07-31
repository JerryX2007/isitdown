import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import App from "./App";

function renderHomePage() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <App />
    </MemoryRouter>,
  );
}

describe("Home page", () => {
  it("renders the website checker", () => {
    renderHomePage();

    expect(
      screen.getByRole("textbox", { name: "Website address" }),
    ).toBeInTheDocument();

    expect(
      screen.getByRole("button", { name: /check status/i }),
    ).toBeInTheDocument();
  });

  it("shows an error when the website is empty", async () => {
    const user = userEvent.setup();
    renderHomePage();

    await user.click(
      screen.getByRole("button", { name: /check status/i }),
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Enter a website to check.",
    );
  });

  it("rejects a local website address", async () => {
    const user = userEvent.setup();
    renderHomePage();

    await user.type(
      screen.getByRole("textbox", { name: "Website address" }),
      "localhost",
    );

    await user.click(
      screen.getByRole("button", { name: /check status/i }),
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Enter a public website address.",
    );
  });
});