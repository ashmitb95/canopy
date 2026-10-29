import { describe, expect, it } from 'vitest'
import type { Question } from '../../src/core/types'
import {
  claudeAnswers,
  codexAnswers,
  elicitationContent,
  elicitationQuestions,
  grokAnswers,
  redactSecrets
} from '../../src/providers/prompts'

const color: Question = {
  id: 'q1',
  question: 'Which color?',
  multiSelect: false,
  allowOther: true,
  options: [
    { id: 'o1', label: 'Red' },
    { id: 'o2', label: 'Blue' }
  ]
}
const sizes: Question = {
  id: 'q2',
  question: 'Which sizes?',
  multiSelect: true,
  allowOther: true,
  options: [
    { id: 'o1', label: 'S' },
    { id: 'o2', label: 'M' }
  ]
}

describe('answer encoders', () => {
  it('encodes Claude answers by question text, comma-joining multi-select and adding typed text', () => {
    expect(
      claudeAnswers(
        [color, sizes],
        [
          { questionId: 'q1', optionIds: ['o2'] },
          { questionId: 'q2', optionIds: ['o1', 'o2'], other: 'XL' }
        ]
      )
    ).toEqual({ 'Which color?': 'Blue', 'Which sizes?': 'S, M, XL' })
  })

  it('encodes Codex answers by question id', () => {
    expect(codexAnswers([color], [{ questionId: 'q1', optionIds: [], other: 'Green' }])).toEqual({
      answers: { q1: { answers: ['Green'] } }
    })
  })

  it('encodes Grok answers with arrays for multi-select and typed text as an annotation', () => {
    expect(
      grokAnswers(
        [color, sizes],
        [
          { questionId: 'q1', optionIds: [], other: 'Green' },
          { questionId: 'q2', optionIds: ['o2'] }
        ]
      )
    ).toEqual({
      outcome: 'accepted',
      answers: { 'Which color?': 'Other', 'Which sizes?': ['M'] },
      annotations: { 'Which color?': { notes: 'Green' } }
    })
  })

  it('redacts typed answers to secret questions before they are stored', () => {
    const secret: Question = { ...color, id: 'q3', secret: true, options: [] }
    expect(redactSecrets([secret], [{ questionId: 'q3', optionIds: [], other: 'hunter2' }])).toEqual([
      { questionId: 'q3', optionIds: [], other: '••••' }
    ])
  })
})

describe('MCP elicitation forms', () => {
  const schema = {
    properties: {
      env: { type: 'string', title: 'Environment', enum: ['staging', 'prod'] },
      confirm: { type: 'boolean', description: 'Apply now?' },
      count: { type: 'integer', title: 'Count' },
      note: { type: 'string' }
    }
  }

  it('turns fields into questions', () => {
    expect(elicitationQuestions(schema)).toEqual([
      {
        id: 'env',
        header: 'Environment',
        question: 'Environment',
        multiSelect: false,
        allowOther: false,
        options: [
          { id: '0', label: 'staging' },
          { id: '1', label: 'prod' }
        ]
      },
      {
        id: 'confirm',
        header: 'confirm',
        question: 'Apply now?',
        multiSelect: false,
        allowOther: false,
        options: [
          { id: '0', label: 'Yes' },
          { id: '1', label: 'No' }
        ]
      },
      { id: 'count', header: 'Count', question: 'Count', multiSelect: false, allowOther: true, options: [] },
      { id: 'note', header: 'note', question: 'note', multiSelect: false, allowOther: true, options: [] }
    ])
  })

  it('turns answers back into typed content', () => {
    const questions = elicitationQuestions(schema)
    expect(
      elicitationContent(schema, questions, [
        { questionId: 'env', optionIds: ['1'] },
        { questionId: 'confirm', optionIds: ['0'] },
        { questionId: 'count', optionIds: [], other: '3' },
        { questionId: 'note', optionIds: [], other: 'ship it' }
      ])
    ).toEqual({ env: 'prod', confirm: true, count: 3, note: 'ship it' })
  })
})
