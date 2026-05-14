import type {
  FieldErrors,
  FieldValues,
  Resolver,
  ResolverResult,
} from 'react-hook-form'

/* Typed Zod v4 resolver for react-hook-form.
 *
 * The official @hookform/resolvers/zod has overload-resolution issues
 * with Zod v4 schemas built via `z.object({...})` (the inferred internals
 * don't match the resolver's `$ZodType<O, I>` overload), so we adapt
 * `safeParseAsync` directly through a structural interface. */

type ZodIssue = {
  path: ReadonlyArray<PropertyKey>
  code: string
  message: string
}

type ZodParseResult<TOut> =
  | { success: true; data: TOut }
  | { success: false; error: { issues: ReadonlyArray<ZodIssue> } }

type ZodSchemaLike<TOut> = {
  safeParseAsync: (value: unknown) => Promise<ZodParseResult<TOut>>
}

export function zodResolver<
  TInput extends FieldValues,
  TOutput extends FieldValues = TInput,
>(schema: ZodSchemaLike<TOutput>): Resolver<TInput, unknown, TOutput> {
  return async (values): Promise<ResolverResult<TInput, TOutput>> => {
    const result = await schema.safeParseAsync(values)
    if (result.success) {
      return { values: result.data, errors: {} }
    }
    const errors: FieldErrors<TInput> = {}
    for (const issue of result.error.issues) {
      if (issue.path.length === 0) continue
      let target = errors as Record<string, unknown>
      for (let i = 0; i < issue.path.length - 1; i += 1) {
        const segment = pathKey(issue.path[i])
        if (segment == null) continue
        const next = (target[segment] ?? {}) as Record<string, unknown>
        target[segment] = next
        target = next
      }
      const leaf = pathKey(issue.path[issue.path.length - 1])
      if (leaf == null) continue
      target[leaf] = { type: issue.code, message: issue.message }
    }
    return { values: {}, errors }
  }
}

function pathKey(value: PropertyKey): string | null {
  if (typeof value === 'symbol') return null
  return String(value)
}
