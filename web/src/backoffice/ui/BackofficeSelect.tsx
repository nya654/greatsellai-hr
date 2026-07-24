import { lazy, Suspense } from "react";

const SemiSelect = lazy(() => import("@douyinfe/semi-ui-19/lib/es/select"));

export interface BackofficeSelectOption {
  label: string;
  value: string;
}

interface BackofficeSelectProps {
  ariaDescribedBy?: string;
  ariaLabelledBy?: string;
  className?: string;
  disabled?: boolean;
  id?: string;
  onChange: (value: string) => void;
  options: BackofficeSelectOption[];
  placeholder?: string;
  value: string;
}

/** A small, controlled select adapter for backoffice forms and toolbars. */
export function BackofficeSelect({
  ariaDescribedBy,
  ariaLabelledBy,
  className,
  disabled = false,
  id,
  onChange,
  options,
  placeholder,
  value,
}: BackofficeSelectProps) {
  const selectClassName = ["backoffice-select", className].filter(Boolean).join(" ");
  const fallback = (
    <select
      aria-describedby={ariaDescribedBy}
      className={`select-field ${selectClassName}`}
      disabled={disabled}
      id={id}
      onChange={(event) => onChange(event.target.value)}
      value={value}
    >
      {placeholder && <option value="">{placeholder}</option>}
      {options.map((option) => (
        <option key={option.value} value={option.value}>{option.label}</option>
      ))}
    </select>
  );

  return (
    <Suspense fallback={fallback}>
      <SemiSelect
        aria-describedby={ariaDescribedBy}
        aria-labelledby={ariaLabelledBy}
        className={selectClassName}
        disabled={disabled}
        onChange={(nextValue) => onChange(typeof nextValue === "string" ? nextValue : "")}
        optionList={options}
        placeholder={placeholder}
        value={value}
      />
    </Suspense>
  );
}
