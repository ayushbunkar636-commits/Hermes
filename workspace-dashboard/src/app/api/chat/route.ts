import { NextResponse } from 'next/server';
import pool from '@/lib/db';

export async function POST(request: Request) {
  try {
    const { message } = await request.json();
    
    // In a full production system, this would call an LLM (e.g. Gemini) with the user message
    // and context from the Supabase database. For this phase, we provide a deterministic analytical response.
    
    const client = await pool.connect();
    
    let aiResponse = "I'm not sure how to help with that. Try asking about 'pending opportunities' or 'highest impact'.";
    
    const lowerMsg = message.toLowerCase();
    
    if (lowerMsg.includes('pending')) {
      const result = await client.query("SELECT COUNT(*) FROM opportunities WHERE status = 'pending'");
      aiResponse = `You currently have ${result.rows[0].count} pending opportunities waiting for approval. Would you like to review them?`;
    } 
    else if (lowerMsg.includes('highest impact') || lowerMsg.includes('top')) {
      const result = await client.query("SELECT title, score_100 FROM opportunities WHERE status = 'approved' ORDER BY score_100 DESC LIMIT 3");
      const tops = result.rows.map((r: any) => `- ${r.title} (Score: ${r.score_100})`);
      aiResponse = `Here are the top opportunities:\n\n${tops.join('\n')}`;
    }
    else if (lowerMsg.includes('hello') || lowerMsg.includes('hi')) {
      aiResponse = "Hello! I am Hermes AI. I can analyze your backlink database. Ask me about pending cards, top platforms, or highest impact opportunities.";
    }

    client.release();

    // Small delay to simulate AI thinking
    await new Promise(resolve => setTimeout(resolve, 800));

    return NextResponse.json({ reply: aiResponse });
  } catch (err: any) {
    return NextResponse.json({ error: err.message }, { status: 500 });
  }
}
