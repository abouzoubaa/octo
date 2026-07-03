import { createQwikCity } from "@builder.io/qwik-city/middleware/node";
import qwikCityPlan from "@qwik-city-plan";
import { manifest } from "@qwik-client-manifest";
import express from "express";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import render from "./entry.ssr";

declare global {
  interface QwikCityPlatform {}
}

const distDir = join(fileURLToPath(import.meta.url), "..", "..", "dist");
const buildDir = join(distDir, "build");

const { router, notFound } = createQwikCity({ render, qwikCityPlan, manifest });

const app = express();
app.use(`/build`, express.static(buildDir, { immutable: true, maxAge: "1y" }));
app.use(express.static(distDir, { redirect: false }));
app.use(router);
app.use(notFound);

const PORT = process.env.PORT ?? 3000;
app.listen(PORT, () => {
  console.log(`cci-web listening on http://localhost:${PORT}`);
});
