import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { LoginPage } from "./LoginPage";

const auth = vi.hoisted(() => ({
  login: vi.fn(),
}));

vi.mock("../auth/AuthProvider", () => ({
  useAuth: () => ({ user: null, login: auth.login }),
}));

describe("LoginPage", () => {
  beforeEach(() => {
    auth.login.mockReset();
    auth.login.mockResolvedValue({
      user_id: "demo-producer",
      email: "producer.demo@relay.local",
      display_name: "Demo Producer",
      roles: ["PRODUCER"],
    });
  });

  it("explains every role and fills scoped demo credentials", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/login"]}>
        <LoginPage />
      </MemoryRouter>,
    );

    for (const role of ["Publisher", "Producer", "Worker", "Administrator"])
      expect(screen.getByRole("heading", { name: role })).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Use Producer demo account" }),
    );
    expect(screen.getByLabelText("Email")).toHaveValue(
      "producer.demo@relay.local",
    );
    expect(screen.getByLabelText("Password")).toHaveValue(
      "relay-demo-password",
    );

    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(auth.login).toHaveBeenCalledWith(
      "producer.demo@relay.local",
      "relay-demo-password",
    );
  });
});
