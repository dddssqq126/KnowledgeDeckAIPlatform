import MockAdapter from "axios-mock-adapter";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { api } from "./api";
import { recordLoginRecord } from "./login-records";

describe("login record client", () => {
  let mock: MockAdapter;

  beforeEach(() => {
    mock = new MockAdapter(api);
  });

  afterEach(() => {
    mock.restore();
  });

  it("posts the current user metadata to the login record API", async () => {
    let requestBody: unknown = null;
    mock.onPost("/auth/login-records").reply((config) => {
      requestBody = JSON.parse(config.data as string);
      return [201, {}];
    });

    await recordLoginRecord({
      DeptName: "IT",
      Chinesename: "王小明",
      DeptID: "D001",
      EmpId: "E123",
      UserAccountName: "ming.wang",
    });

    expect(requestBody).toEqual({
      DeptName: "IT",
      Chinesename: "王小明",
      DeptID: "D001",
      EmpId: "E123",
      UserAccountName: "ming.wang",
    });
  });

  it("skips the API call when UserAccountName is empty", async () => {
    mock.onPost("/auth/login-records").reply(201, {});

    await recordLoginRecord({
      DeptName: null,
      Chinesename: null,
      DeptID: null,
      EmpId: null,
      UserAccountName: "",
    });

    expect(mock.history.post).toHaveLength(0);
  });
});
