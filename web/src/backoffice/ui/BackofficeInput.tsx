import { lazy, Suspense, type ChangeEvent, type InputHTMLAttributes } from "react";
import type { InputProps as SemiInputProps } from "@douyinfe/semi-ui-19/lib/es/input";

const SemiInput = lazy(() => import("@douyinfe/semi-ui-19/lib/es/input"));

type NativeInputProps = Omit<
  InputHTMLAttributes<HTMLInputElement>,
  "className" | "onChange" | "size" | "value"
>;

interface BackofficeInputProps extends NativeInputProps {
  className?: string;
  onChange?: (value: string, event: ChangeEvent<HTMLInputElement>) => void;
  value?: string;
}

/**
 * Keeps Semi's input behavior inside the authenticated workspace while
 * preserving the native field attributes used by existing feature forms.
 */
export function BackofficeInput({
  className,
  onChange,
  value = "",
  ...props
}: BackofficeInputProps) {
  const inputClassName = ["backoffice-input", className].filter(Boolean).join(" ");
  const fallback = (
    <input
      {...props}
      className={`field ${inputClassName}`}
      onChange={(event) => onChange?.(event.target.value, event)}
      value={value}
    />
  );

  return (
    <Suspense fallback={fallback}>
      <SemiInput
        {...(props as Omit<SemiInputProps, "className" | "onChange" | "value">)}
        className={inputClassName}
        onChange={(nextValue, event) => onChange?.(nextValue, event)}
        value={value}
      />
    </Suspense>
  );
}
