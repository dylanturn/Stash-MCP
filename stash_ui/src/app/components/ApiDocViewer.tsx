import React, { useState, useEffect } from 'react';
import SwaggerUI from 'swagger-ui-react';
import 'swagger-ui-react/swagger-ui.css';

interface ApiDocViewerProps {
  spec: string;
}

export function ApiDocViewer({ spec }: ApiDocViewerProps) {
  const [error, setError] = useState<string | null>(null);
  const [parsedSpec, setParsedSpec] = useState<any>(null);

  useEffect(() => {
    try {
      const specObj = JSON.parse(spec);
      setParsedSpec(specObj);
      setError(null);
    } catch (e) {
      console.error('Failed to parse OpenAPI spec:', e);
      setError('Invalid OpenAPI specification format');
    }
  }, [spec]);

  if (error) {
    return (
      <div className="h-full w-full flex items-center justify-center p-8" style={{ backgroundColor: 'var(--stash-bg-base)' }}>
        <div className="text-center">
          <p style={{ color: 'var(--stash-error)' }} className="mb-2">
            {error}
          </p>
          <p style={{ color: 'var(--stash-text-secondary)' }} className="text-sm">
            Please check that the file contains valid OpenAPI 3.0 or Swagger 2.0 JSON
          </p>
        </div>
      </div>
    );
  }

  if (!parsedSpec) {
    return (
      <div className="h-full w-full flex items-center justify-center" style={{ backgroundColor: 'var(--stash-bg-base)' }}>
        <p style={{ color: 'var(--stash-text-secondary)' }}>Loading API documentation...</p>
      </div>
    );
  }

  return (
    <div className="h-full w-full overflow-auto swagger-ui-wrapper" style={{ backgroundColor: 'var(--stash-bg-base)' }}>
      <style>{`
        .swagger-ui-wrapper .swagger-ui {
          font-family: Inter, system-ui, sans-serif;
        }
        
        .swagger-ui-wrapper .swagger-ui .topbar {
          display: none;
        }
        
        .swagger-ui-wrapper .swagger-ui .info {
          margin: 30px 0;
        }
        
        .swagger-ui-wrapper .swagger-ui .scheme-container {
          background: var(--stash-bg-surface);
          box-shadow: none;
          border: 1px solid var(--stash-border);
        }
        
        .swagger-ui-wrapper .swagger-ui .opblock-tag {
          border-bottom: 1px solid var(--stash-border);
          color: var(--stash-text-bright);
        }
        
        .swagger-ui-wrapper .swagger-ui .opblock {
          border: 1px solid var(--stash-border);
          background: var(--stash-bg-surface);
          box-shadow: none;
          margin-bottom: 15px;
        }
        
        .swagger-ui-wrapper .swagger-ui .opblock.opblock-get {
          border-color: #94e2d5;
          background: rgba(148, 226, 213, 0.1);
        }
        
        .swagger-ui-wrapper .swagger-ui .opblock.opblock-post {
          border-color: #a6e3a1;
          background: rgba(166, 227, 161, 0.1);
        }
        
        .swagger-ui-wrapper .swagger-ui .opblock.opblock-put {
          border-color: #f9e2af;
          background: rgba(249, 226, 175, 0.1);
        }
        
        .swagger-ui-wrapper .swagger-ui .opblock.opblock-delete {
          border-color: #f38ba8;
          background: rgba(243, 139, 168, 0.1);
        }
        
        .swagger-ui-wrapper .swagger-ui .opblock .opblock-summary-method {
          background: var(--stash-accent);
          color: var(--stash-bg-base);
          font-weight: 600;
        }
        
        .swagger-ui-wrapper .swagger-ui .opblock.opblock-get .opblock-summary-method {
          background: #94e2d5;
        }
        
        .swagger-ui-wrapper .swagger-ui .opblock.opblock-post .opblock-summary-method {
          background: #a6e3a1;
        }
        
        .swagger-ui-wrapper .swagger-ui .opblock.opblock-put .opblock-summary-method {
          background: #f9e2af;
        }
        
        .swagger-ui-wrapper .swagger-ui .opblock.opblock-delete .opblock-summary-method {
          background: #f38ba8;
        }
        
        .swagger-ui-wrapper .swagger-ui .opblock .opblock-summary-path {
          color: var(--stash-text-bright);
        }
        
        .swagger-ui-wrapper .swagger-ui .opblock .opblock-summary-description {
          color: var(--stash-text-secondary);
        }
        
        .swagger-ui-wrapper .swagger-ui .opblock-body pre {
          background: var(--stash-bg-base);
          color: var(--stash-text-bright);
          border: 1px solid var(--stash-border);
        }
        
        .swagger-ui-wrapper .swagger-ui .parameter__name,
        .swagger-ui-wrapper .swagger-ui .parameter__type {
          color: var(--stash-text-bright);
        }
        
        .swagger-ui-wrapper .swagger-ui .response-col_status {
          color: var(--stash-text-bright);
        }
        
        .swagger-ui-wrapper .swagger-ui .response-col_description {
          color: var(--stash-text-secondary);
        }
        
        .swagger-ui-wrapper .swagger-ui table thead tr th,
        .swagger-ui-wrapper .swagger-ui table thead tr td {
          color: var(--stash-text-bright);
          border-bottom: 1px solid var(--stash-border);
        }
        
        .swagger-ui-wrapper .swagger-ui .btn {
          background: var(--stash-accent);
          color: var(--stash-bg-base);
          border: none;
          font-weight: 600;
        }
        
        .swagger-ui-wrapper .swagger-ui .btn:hover {
          opacity: 0.9;
        }
        
        .swagger-ui-wrapper .swagger-ui .info .title,
        .swagger-ui-wrapper .swagger-ui .info h1,
        .swagger-ui-wrapper .swagger-ui .info h2,
        .swagger-ui-wrapper .swagger-ui .info h3 {
          color: var(--stash-text-bright);
        }
        
        .swagger-ui-wrapper .swagger-ui .info p,
        .swagger-ui-wrapper .swagger-ui .info li {
          color: var(--stash-text-secondary);
        }
        
        .swagger-ui-wrapper .swagger-ui .markdown p,
        .swagger-ui-wrapper .swagger-ui .markdown code {
          color: var(--stash-text-secondary);
        }
        
        .swagger-ui-wrapper .swagger-ui .model-box {
          background: var(--stash-bg-surface);
          border: 1px solid var(--stash-border);
        }
        
        .swagger-ui-wrapper .swagger-ui .model-title {
          color: var(--stash-text-bright);
        }
        
        .swagger-ui-wrapper .swagger-ui .prop-type {
          color: #94e2d5;
        }
        
        .swagger-ui-wrapper .swagger-ui .prop-format {
          color: #bac2de;
        }
        
        .swagger-ui-wrapper .swagger-ui section.models {
          border: 1px solid var(--stash-border);
          background: var(--stash-bg-surface);
        }
        
        .swagger-ui-wrapper .swagger-ui section.models h4 {
          color: var(--stash-text-bright);
        }
        
        .swagger-ui-wrapper .swagger-ui .model-container {
          background: var(--stash-bg-base);
        }
      `}</style>
      <SwaggerUI 
        spec={parsedSpec}
        docExpansion="list"
        defaultModelsExpandDepth={1}
        displayRequestDuration={true}
        filter={true}
        showExtensions={true}
        showCommonExtensions={true}
      />
    </div>
  );
}
