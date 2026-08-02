"use server";

import { revalidatePath } from "next/cache";

import { ApiError, del, patch, post } from "@/lib/api/server";

export type ActionResult = { ok: true; message?: string } | { ok: false; error: string };

function fail(error: unknown): { ok: false; error: string } {
  if (error instanceof ApiError) return { ok: false, error: error.message };
  return { ok: false, error: "Something went wrong. Please try again." };
}

export async function inviteAdmin(
  email: string,
  name: string,
  role: string,
  permissions: string[],
): Promise<ActionResult> {
  try {
    const result = await post<{ message: string }>("/api/admin/admins", {
      email: email.trim().toLowerCase(),
      name: name.trim() || null,
      role,
      // Sent explicitly rather than letting the server expand the role, so what
      // the inviter saw ticked is exactly what gets stored.
      permissions,
    });
    revalidatePath("/platform/admins");
    return { ok: true, message: result.message };
  } catch (error) {
    return fail(error);
  }
}

export async function updateAdmin(
  adminId: string,
  role: string,
  permissions: string[],
): Promise<ActionResult> {
  try {
    await patch(`/api/admin/admins/${adminId}`, { role, permissions });
    revalidatePath("/platform/admins");
    return { ok: true };
  } catch (error) {
    return fail(error);
  }
}

export async function revokeAdmin(adminId: string): Promise<ActionResult> {
  try {
    await del(`/api/admin/admins/${adminId}`);
    revalidatePath("/platform/admins");
    return { ok: true };
  } catch (error) {
    return fail(error);
  }
}
