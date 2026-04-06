import OpenAI from 'openai';
import { config } from '../config.js';

const client = new OpenAI({ apiKey: config.openaiApiKey });

export async function embedText(text: string): Promise<number[]> {
  const response = await client.embeddings.create({
    model: config.openaiEmbeddingModel,
    input: text,
  });
  return response.data[0].embedding;
}

export async function embedTexts(texts: string[]): Promise<number[][]> {
  if (texts.length === 0) return [];

  const response = await client.embeddings.create({
    model: config.openaiEmbeddingModel,
    input: texts,
  });
  return response.data.map((d) => d.embedding);
}
