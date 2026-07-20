import { z } from "zod";

export const passwordSchema = z
  .string()
  .min(8, "Minimum 8 characters")
  .regex(/\d/, "At least one digit");

export const loginSchema = z.object({
  email: z.string().email("Enter a valid email"),
  password: z.string().min(1, "Required"),
});

export const registerSchema = z
  .object({
    email: z.string().email("Enter a valid email"),
    first_name: z.string().min(1, "Required"),
    last_name: z.string().min(1, "Required"),
    password: passwordSchema,
    password_confirm: z.string(),
    accept_tos: z
      .boolean()
      .refine((v) => v === true, "You must accept the terms"),
  })
  .refine((d) => d.password === d.password_confirm, {
    message: "Passwords do not match",
    path: ["password_confirm"],
  });

export const forgotSchema = z.object({
  email: z.string().email("Enter a valid email"),
});

export const resetSchema = z
  .object({
    password: passwordSchema,
    password_confirm: z.string(),
  })
  .refine((d) => d.password === d.password_confirm, {
    message: "Passwords do not match",
    path: ["password_confirm"],
  });

export const profileUpdateSchema = z.object({
  first_name: z.string().min(1, "Required").optional(),
  last_name: z.string().min(1, "Required").optional(),
});
export type ProfileUpdate = z.infer<typeof profileUpdateSchema>;

export const userSchema = z.object({
  id: z.string(),
  email: z.string().email(),
  first_name: z.string(),
  last_name: z.string(),
  role: z.string(),
  email_verified: z.boolean().optional(),
  is_verified: z.boolean().optional(),
  plan_slug: z.string().optional().nullable(),
  plan_features: z.record(z.unknown()).optional(),
  plan_limits: z.record(z.unknown()).optional(),
});
export type User = z.infer<typeof userSchema>;

export type LoginInput = z.infer<typeof loginSchema>;
export type RegisterInput = z.infer<typeof registerSchema>;
export type ForgotInput = z.infer<typeof forgotSchema>;
export type ResetInput = z.infer<typeof resetSchema>;
