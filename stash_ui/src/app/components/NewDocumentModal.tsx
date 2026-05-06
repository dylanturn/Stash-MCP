import React, { useState } from 'react';
import { X } from 'lucide-react';

interface NewDocumentModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCreate: (path: string, content: string, template: string) => void;
}

export function NewDocumentModal({ isOpen, onClose, onCreate }: NewDocumentModalProps) {
  const [path, setPath] = useState('');
  const [template, setTemplate] = useState('blank');
  const [content, setContent] = useState('');

  const templates = {
    blank: { name: 'Blank Document', content: '' },
    notes: {
      name: 'Meeting Notes',
      content: `# Meeting Notes - ${new Date().toLocaleDateString()}

**Attendees:**
- 

**Agenda:**
1. 
2. 
3. 

---

## Discussion Points

### Topic 1


### Topic 2


---

## Action Items

- [ ] 
- [ ] 

---

**Next Meeting:** [Date/Time]`
    },
    spec: {
      name: 'API Specification',
      content: `# API Specification

## Overview

[Brief description of the API]

## Endpoints

### GET /endpoint

**Description:** 

**Parameters:**
- \`param1\` (string, required): Description

**Response:**
\`\`\`json
{
  "status": "success",
  "data": {}
}
\`\`\`

### POST /endpoint

**Description:** 

**Request Body:**
\`\`\`json
{
  "field": "value"
}
\`\`\`

**Response:**
\`\`\`json
{
  "status": "success",
  "message": "Created successfully"
}
\`\`\``
    },
    readme: {
      name: 'README',
      content: `# Project Name

## Overview

[Brief description of the project]

## Installation

\`\`\`bash
npm install
\`\`\`

## Usage

[How to use the project]

## Features

- Feature 1
- Feature 2
- Feature 3

## Contributing

[Contribution guidelines]

## License

[License information]`
    }
  };

  const handleCreate = () => {
    if (!path.trim()) return;
    
    const selectedTemplate = templates[template as keyof typeof templates];
    const finalContent = content || selectedTemplate.content;
    
    onCreate(path, finalContent, template);
    
    // Reset form
    setPath('');
    setTemplate('blank');
    setContent('');
  };

  const handleTemplateChange = (newTemplate: string) => {
    setTemplate(newTemplate);
    setContent(templates[newTemplate as keyof typeof templates].content);
  };

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 flex items-center justify-center z-50"
      style={{ backgroundColor: 'rgba(0, 0, 0, 0.6)' }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl rounded-lg shadow-2xl"
        style={{ backgroundColor: 'var(--stash-bg-elevated)' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between p-6 border-b"
          style={{ borderColor: 'var(--stash-border)' }}
        >
          <h2 className="text-lg" style={{ color: 'var(--stash-text-bright)' }}>
            New Document
          </h2>
          <button
            onClick={onClose}
            className="p-1 rounded transition-all duration-150"
            style={{ color: 'var(--stash-text-secondary)' }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent';
            }}
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-6 space-y-4">
          {/* Path Input */}
          <div>
            <label className="block text-sm mb-2" style={{ color: 'var(--stash-text-primary)' }}>
              File Path
            </label>
            <input
              type="text"
              value={path}
              onChange={(e) => setPath(e.target.value)}
              placeholder="/docs/my-document.md"
              className="w-full px-4 py-2 rounded-md text-sm outline-none transition-all duration-150"
              style={{
                backgroundColor: 'var(--stash-bg-base)',
                color: 'var(--stash-text-primary)',
                border: '1px solid var(--stash-border)'
              }}
              onFocus={(e) => {
                e.currentTarget.style.borderColor = 'var(--stash-accent)';
                e.currentTarget.style.boxShadow = '0 0 0 2px rgba(148, 226, 213, 0.1)';
              }}
              onBlur={(e) => {
                e.currentTarget.style.borderColor = 'var(--stash-border)';
                e.currentTarget.style.boxShadow = 'none';
              }}
            />
            <p className="text-xs mt-1" style={{ color: 'var(--stash-text-secondary)' }}>
              Include the full path and filename. Directories will be created automatically.
            </p>
          </div>

          {/* Template Selector */}
          <div>
            <label className="block text-sm mb-2" style={{ color: 'var(--stash-text-primary)' }}>
              Template
            </label>
            <div className="grid grid-cols-2 gap-2">
              {Object.entries(templates).map(([key, { name }]) => (
                <button
                  key={key}
                  onClick={() => handleTemplateChange(key)}
                  className="px-4 py-2 rounded-md text-sm transition-all duration-150"
                  style={{
                    backgroundColor: template === key ? 'var(--stash-accent)' : 'var(--stash-bg-surface)',
                    color: template === key ? 'var(--stash-bg-base)' : 'var(--stash-text-primary)',
                    border: `1px solid ${template === key ? 'var(--stash-accent)' : 'var(--stash-border)'}`
                  }}
                >
                  {name}
                </button>
              ))}
            </div>
          </div>

          {/* Content Preview/Editor */}
          <div>
            <label className="block text-sm mb-2" style={{ color: 'var(--stash-text-primary)' }}>
              Initial Content (Optional)
            </label>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="Leave blank to use template content"
              rows={8}
              className="w-full px-4 py-3 rounded-md text-sm font-mono resize-none outline-none transition-all duration-150"
              style={{
                backgroundColor: 'var(--stash-bg-base)',
                color: 'var(--stash-text-primary)',
                border: '1px solid var(--stash-border)',
                lineHeight: '1.6'
              }}
              onFocus={(e) => {
                e.currentTarget.style.borderColor = 'var(--stash-accent)';
                e.currentTarget.style.boxShadow = '0 0 0 2px rgba(148, 226, 213, 0.1)';
              }}
              onBlur={(e) => {
                e.currentTarget.style.borderColor = 'var(--stash-border)';
                e.currentTarget.style.boxShadow = 'none';
              }}
            />
          </div>
        </div>

        {/* Footer */}
        <div
          className="flex items-center justify-end gap-3 p-6 border-t"
          style={{ borderColor: 'var(--stash-border)' }}
        >
          <button
            onClick={onClose}
            className="px-6 py-2 rounded-md text-sm transition-all duration-150"
            style={{
              backgroundColor: 'transparent',
              color: 'var(--stash-text-secondary)',
              border: '1px solid var(--stash-border)'
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--stash-bg-hover)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent';
            }}
          >
            Cancel
          </button>
          <button
            onClick={handleCreate}
            disabled={!path.trim()}
            className="px-6 py-2 rounded-md text-sm transition-all duration-150"
            style={{
              backgroundColor: path.trim() ? 'var(--stash-accent)' : 'var(--stash-bg-surface)',
              color: path.trim() ? 'var(--stash-bg-base)' : 'var(--stash-text-secondary)',
              opacity: path.trim() ? '1' : '0.5',
              cursor: path.trim() ? 'pointer' : 'not-allowed'
            }}
            onMouseEnter={(e) => {
              if (path.trim()) e.currentTarget.style.opacity = '0.9';
            }}
            onMouseLeave={(e) => {
              if (path.trim()) e.currentTarget.style.opacity = '1';
            }}
          >
            Create Document
          </button>
        </div>
      </div>
    </div>
  );
}
