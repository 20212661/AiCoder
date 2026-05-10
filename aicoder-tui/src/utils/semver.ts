import { gt as semverGt, gte as semverGte, lt as semverLt, lte as semverLte, satisfies as semverSatisfies, compare } from 'semver'

export function gt(a: string, b: string): boolean {
  return semverGt(a, b, { loose: true })
}

export function gte(a: string, b: string): boolean {
  return semverGte(a, b, { loose: true })
}

export function lt(a: string, b: string): boolean {
  return semverLt(a, b, { loose: true })
}

export function lte(a: string, b: string): boolean {
  return semverLte(a, b, { loose: true })
}

export function satisfies(version: string, range: string): boolean {
  return semverSatisfies(version, range, { loose: true })
}

export function order(a: string, b: string): -1 | 0 | 1 {
  return compare(a, b, { loose: true }) as -1 | 0 | 1
}
