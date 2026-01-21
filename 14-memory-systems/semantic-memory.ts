/**
 * Lesson 14: Semantic Memory
 *
 * Manages facts and knowledge as structured entries.
 * Supports simple knowledge graph operations.
 */

import type {
  MemoryStore,
  MemoryEntry,
  Fact,
  Concept,
} from './types.js';
import { generateMemoryId } from './memory-store.js';

// =============================================================================
// SEMANTIC MEMORY MANAGER
// =============================================================================

/**
 * Manages semantic memory (facts and knowledge).
 */
export class SemanticMemory {
  private store: MemoryStore;
  private concepts: Map<string, Concept> = new Map();

  constructor(store: MemoryStore) {
    this.store = store;
  }

  // ===========================================================================
  // FACT MANAGEMENT
  // ===========================================================================

  /**
   * Learn a new fact.
   */
  async learnFact(
    statement: string,
    options: {
      subject?: string;
      predicate?: string;
      object?: string;
      confidence?: number;
      source?: string;
    } = {}
  ): Promise<Fact> {
    // Parse fact into subject-predicate-object if not provided
    const parsed = this.parseFact(statement);

    const fact: Fact = {
      id: generateMemoryId('fact'),
      statement,
      subject: options.subject || parsed.subject,
      predicate: options.predicate || parsed.predicate,
      object: options.object || parsed.object,
      confidence: options.confidence ?? 0.8,
      source: options.source || 'learned',
      learnedAt: new Date(),
    };

    // Store as memory
    await this.storeFactAsMemory(fact);

    // Update concept graph
    await this.linkFactToConcepts(fact);

    return fact;
  }

  /**
   * Update fact confidence.
   */
  async updateFactConfidence(factId: string, newConfidence: number): Promise<void> {
    const memory = await this.store.get(factId);
    if (memory) {
      const fact = this.memoryToFact(memory);
      fact.confidence = Math.max(0, Math.min(1, newConfidence));
      fact.verifiedAt = new Date();

      await this.store.update(factId, {
        content: JSON.stringify(fact),
        importance: this.calculateFactImportance(fact),
      });
    }
  }

  /**
   * Verify a fact (confirm it's still true).
   */
  async verifyFact(factId: string, stillTrue: boolean): Promise<void> {
    const memory = await this.store.get(factId);
    if (memory) {
      const fact = this.memoryToFact(memory);

      if (stillTrue) {
        fact.confidence = Math.min(1, fact.confidence + 0.1);
        fact.verifiedAt = new Date();
      } else {
        // Decrease confidence significantly
        fact.confidence = Math.max(0, fact.confidence - 0.3);
      }

      await this.store.update(factId, {
        content: JSON.stringify(fact),
        importance: this.calculateFactImportance(fact),
      });
    }
  }

  /**
   * Get facts about a subject.
   */
  async getFactsAbout(subject: string): Promise<Fact[]> {
    const memories = await this.store.query({
      type: 'semantic',
      sortBy: 'importance',
      sortOrder: 'desc',
    });

    const subjectLower = subject.toLowerCase();

    return memories
      .map((m) => this.memoryToFact(m))
      .filter((f) =>
        f.subject.toLowerCase().includes(subjectLower) ||
        f.object.toLowerCase().includes(subjectLower)
      );
  }

  /**
   * Search facts by statement content.
   */
  async searchFacts(query: string, limit = 10): Promise<Fact[]> {
    const memories = await this.store.query({
      type: 'semantic',
      sortBy: 'importance',
      sortOrder: 'desc',
    });

    const queryLower = query.toLowerCase();

    return memories
      .map((m) => this.memoryToFact(m))
      .filter((f) => f.statement.toLowerCase().includes(queryLower))
      .slice(0, limit);
  }

  /**
   * Get related facts.
   */
  async getRelatedFacts(fact: Fact, limit = 5): Promise<Fact[]> {
    const memories = await this.store.query({
      type: 'semantic',
      sortBy: 'importance',
      sortOrder: 'desc',
    });

    const subjectLower = fact.subject.toLowerCase();
    const objectLower = fact.object.toLowerCase();

    return memories
      .map((m) => this.memoryToFact(m))
      .filter((f) => {
        if (f.id === fact.id) return false;

        // Related if shares subject or object
        const fSubject = f.subject.toLowerCase();
        const fObject = f.object.toLowerCase();

        return (
          fSubject === subjectLower ||
          fSubject === objectLower ||
          fObject === subjectLower ||
          fObject === objectLower
        );
      })
      .slice(0, limit);
  }

  // ===========================================================================
  // CONCEPT MANAGEMENT
  // ===========================================================================

  /**
   * Create or get a concept.
   */
  async ensureConcept(name: string, description?: string): Promise<Concept> {
    const existing = this.concepts.get(name.toLowerCase());
    if (existing) return existing;

    const concept: Concept = {
      id: generateMemoryId('concept'),
      name,
      description: description || `Concept: ${name}`,
      relatedConcepts: [],
      facts: [],
    };

    this.concepts.set(name.toLowerCase(), concept);
    return concept;
  }

  /**
   * Link two concepts.
   */
  async linkConcepts(concept1: string, concept2: string): Promise<void> {
    const c1 = await this.ensureConcept(concept1);
    const c2 = await this.ensureConcept(concept2);

    if (!c1.relatedConcepts.includes(c2.id)) {
      c1.relatedConcepts.push(c2.id);
    }
    if (!c2.relatedConcepts.includes(c1.id)) {
      c2.relatedConcepts.push(c1.id);
    }
  }

  /**
   * Get concept by name.
   */
  getConcept(name: string): Concept | undefined {
    return this.concepts.get(name.toLowerCase());
  }

  /**
   * Get all concepts.
   */
  getAllConcepts(): Concept[] {
    return Array.from(this.concepts.values());
  }

  /**
   * Get concepts related to a concept.
   */
  getRelatedConcepts(conceptName: string): Concept[] {
    const concept = this.concepts.get(conceptName.toLowerCase());
    if (!concept) return [];

    return concept.relatedConcepts
      .map((id) => {
        for (const c of this.concepts.values()) {
          if (c.id === id) return c;
        }
        return null;
      })
      .filter((c): c is Concept => c !== null);
  }

  // ===========================================================================
  // KNOWLEDGE QUERIES
  // ===========================================================================

  /**
   * Answer a simple question using stored facts.
   */
  async answerQuestion(question: string): Promise<{
    answer: string | null;
    confidence: number;
    facts: Fact[];
  }> {
    // Parse question to extract subject
    const parsed = this.parseQuestion(question);

    if (!parsed.subject) {
      return { answer: null, confidence: 0, facts: [] };
    }

    // Find relevant facts
    const facts = await this.getFactsAbout(parsed.subject);

    if (facts.length === 0) {
      return { answer: null, confidence: 0, facts: [] };
    }

    // Find best matching fact based on question type
    let bestFact: Fact | null = null;
    let bestScore = 0;

    for (const fact of facts) {
      let score = fact.confidence;

      // Boost if predicate matches question type
      if (parsed.questionType === 'what' && fact.predicate.includes('is')) {
        score += 0.2;
      } else if (parsed.questionType === 'where' && fact.predicate.includes('located')) {
        score += 0.2;
      } else if (parsed.questionType === 'when' && fact.predicate.includes('date')) {
        score += 0.2;
      }

      if (score > bestScore) {
        bestScore = score;
        bestFact = fact;
      }
    }

    if (bestFact) {
      return {
        answer: bestFact.statement,
        confidence: bestFact.confidence,
        facts: facts.slice(0, 3),
      };
    }

    return { answer: null, confidence: 0, facts };
  }

  /**
   * Check if a statement is known to be true.
   */
  async isKnownTrue(statement: string): Promise<{
    known: boolean;
    confidence: number;
    fact?: Fact;
  }> {
    const facts = await this.searchFacts(statement, 5);

    for (const fact of facts) {
      // Simple similarity check
      const similarity = this.textSimilarity(statement, fact.statement);
      if (similarity > 0.8) {
        return { known: true, confidence: fact.confidence, fact };
      }
    }

    return { known: false, confidence: 0 };
  }

  // ===========================================================================
  // HELPERS
  // ===========================================================================

  /**
   * Store fact as memory entry.
   */
  private async storeFactAsMemory(fact: Fact): Promise<void> {
    const importance = this.calculateFactImportance(fact);

    const entry: MemoryEntry = {
      id: fact.id,
      type: 'semantic',
      content: JSON.stringify(fact),
      importance,
      createdAt: fact.learnedAt,
      lastAccessed: new Date(),
      accessCount: 0,
      metadata: {
        source: fact.source === 'user' ? 'user' : 'agent',
        confidence: fact.confidence,
        subject: fact.subject,
        predicate: fact.predicate,
        object: fact.object,
      },
      tags: [fact.subject.toLowerCase(), fact.object.toLowerCase()].filter(Boolean),
      relatedTo: [],
      decayRate: 0.98, // Facts decay slowly
    };

    await this.store.store(entry);
  }

  /**
   * Convert memory to fact.
   */
  private memoryToFact(memory: MemoryEntry): Fact {
    try {
      const fact = JSON.parse(memory.content) as Fact;
      fact.learnedAt = new Date(fact.learnedAt);
      if (fact.verifiedAt) fact.verifiedAt = new Date(fact.verifiedAt);
      return fact;
    } catch {
      return {
        id: memory.id,
        statement: memory.content,
        subject: 'unknown',
        predicate: 'unknown',
        object: 'unknown',
        confidence: memory.importance,
        source: 'unknown',
        learnedAt: memory.createdAt,
      };
    }
  }

  /**
   * Link fact to concepts.
   */
  private async linkFactToConcepts(fact: Fact): Promise<void> {
    // Ensure concepts for subject and object
    const subjectConcept = await this.ensureConcept(fact.subject);
    const objectConcept = await this.ensureConcept(fact.object);

    // Add fact to concepts
    if (!subjectConcept.facts.includes(fact.id)) {
      subjectConcept.facts.push(fact.id);
    }
    if (!objectConcept.facts.includes(fact.id)) {
      objectConcept.facts.push(fact.id);
    }

    // Link concepts
    await this.linkConcepts(fact.subject, fact.object);
  }

  /**
   * Calculate fact importance.
   */
  private calculateFactImportance(fact: Fact): number {
    let importance = fact.confidence * 0.6;

    // Verified facts are more important
    if (fact.verifiedAt) {
      importance += 0.2;
    }

    // Named sources are more important
    if (fact.source && fact.source !== 'learned' && fact.source !== 'unknown') {
      importance += 0.1;
    }

    return Math.min(1, importance);
  }

  /**
   * Parse a statement into subject-predicate-object.
   */
  private parseFact(statement: string): {
    subject: string;
    predicate: string;
    object: string;
  } {
    // Simple parsing - looks for "X is Y" pattern
    const isMatch = statement.match(/^(.+?)\s+(is|are|was|were|has|have|had)\s+(.+)$/i);
    if (isMatch) {
      return {
        subject: isMatch[1].trim(),
        predicate: isMatch[2].toLowerCase(),
        object: isMatch[3].trim(),
      };
    }

    // Try "X verb Y" pattern
    const verbMatch = statement.match(/^(.+?)\s+(\w+(?:s|ed|ing)?)\s+(.+)$/i);
    if (verbMatch) {
      return {
        subject: verbMatch[1].trim(),
        predicate: verbMatch[2].toLowerCase(),
        object: verbMatch[3].trim(),
      };
    }

    // Default - split in half
    const words = statement.split(' ');
    const mid = Math.floor(words.length / 2);
    return {
      subject: words.slice(0, mid).join(' '),
      predicate: 'related_to',
      object: words.slice(mid).join(' '),
    };
  }

  /**
   * Parse a question.
   */
  private parseQuestion(question: string): {
    questionType: 'what' | 'who' | 'where' | 'when' | 'why' | 'how' | 'other';
    subject: string | null;
  } {
    const lower = question.toLowerCase().replace(/[?!.,]/g, '');
    let questionType: 'what' | 'who' | 'where' | 'when' | 'why' | 'how' | 'other' = 'other';
    let subject: string | null = null;

    if (lower.startsWith('what')) questionType = 'what';
    else if (lower.startsWith('who')) questionType = 'who';
    else if (lower.startsWith('where')) questionType = 'where';
    else if (lower.startsWith('when')) questionType = 'when';
    else if (lower.startsWith('why')) questionType = 'why';
    else if (lower.startsWith('how')) questionType = 'how';

    // Extract subject - look for "about X" or "is X"
    const aboutMatch = lower.match(/about\s+(\w+)/);
    if (aboutMatch) {
      subject = aboutMatch[1];
    } else {
      const isMatch = lower.match(/is\s+(\w+)/);
      if (isMatch) {
        subject = isMatch[1];
      } else {
        // Take last noun-like word
        const words = lower.split(/\s+/);
        subject = words[words.length - 1];
      }
    }

    return { questionType, subject };
  }

  /**
   * Simple text similarity (Jaccard).
   */
  private textSimilarity(a: string, b: string): number {
    const setA = new Set(a.toLowerCase().split(/\W+/));
    const setB = new Set(b.toLowerCase().split(/\W+/));

    const intersection = new Set([...setA].filter((x) => setB.has(x)));
    const union = new Set([...setA, ...setB]);

    return union.size > 0 ? intersection.size / union.size : 0;
  }
}

// =============================================================================
// EXPORTS
// =============================================================================

export function createSemanticMemory(store: MemoryStore): SemanticMemory {
  return new SemanticMemory(store);
}
