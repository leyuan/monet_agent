"use client";

import { MarkdownTextPrimitive } from "@assistant-ui/react-markdown";
import remarkGfm from "remark-gfm";

export const MarkdownText = () => (
  <MarkdownTextPrimitive remarkPlugins={[remarkGfm]} />
);
