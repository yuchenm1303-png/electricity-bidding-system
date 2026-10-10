export type SpringValue = { value: number; velocity: number; target: number };

/** Damped second-order spring; frame-independent velocity integration. */
export function stepSpring(spring: SpringValue, dt: number, stiffness: number, damping: number) {
  const acceleration = (spring.target - spring.value) * stiffness;
  spring.velocity += acceleration * dt;
  spring.velocity *= Math.exp(-damping * dt);
  spring.value += spring.velocity * dt;
}
