import { PasswordRecoveryForm } from "@/components/auth/PasswordRecoveryForm"
import { cookies } from "next/headers"
import { redirect } from "next/navigation"

export default async function ResetPasswordPage() {
  if (!(await cookies()).get("socra_recovery")) redirect("/forgot-password?error=expired")
  return <PasswordRecoveryForm mode="reset" />
}
