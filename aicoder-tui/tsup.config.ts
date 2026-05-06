import { defineConfig } from "tsup";

export default defineConfig({
  entry: ["src/index.tsx"],
  format: ["esm"],
  target: "node18",
  platform: "node",
  clean: true,
  splitting: false,
  sourcemap: true,
  dts: true,
  external: ["react", "react-reconciler", "react/jsx-runtime"],
  tsconfig: "./tsconfig.json",
});
