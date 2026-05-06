import { FileNode } from './types';
import { mermaidDemoContent } from './mockData/mermaidExamples';

export const mockFileTree: FileNode[] = [
  {
    id: '1',
    name: 'docs',
    type: 'folder',
    path: '/docs',
    children: [
      {
        id: '1-1',
        name: 'getting-started.md',
        type: 'file',
        path: '/docs/getting-started.md',
        extension: 'md',
        size: 2847,
        lastModified: '2026-02-05T14:32:00Z',
        content: `# Getting Started with Stash-MCP

Welcome to Stash-MCP, your centralized document management system designed for comfort during extended work sessions.

## Quick Start

1. **Creating Documents**: Click the "+ New Document" button in the file tree or right-click a folder to create a new file.
2. **Editing**: Select any file to view it, then click the "Edit" tab to make changes.
3. **Organization**: Files are automatically organized by their path. Create nested folders by using forward slashes in the path.

## Key Features

- **Semi-Dark Theme**: Carefully tuned colors reduce eye strain on large monitors
- **Three-Panel Layout**: Efficient use of screen space without overwhelming content
- **Markdown Support**: Full markdown rendering with syntax highlighting
- **Smart Search**: Filter your file tree instantly as you type

## Tips for Comfort

The semi-dark palette with warm tints is optimized for 27"+ displays. The center panel maintains readable line lengths (60-70 characters) to prevent eye strain from tracking long lines of text.

Take advantage of collapsible panels to focus on what matters. The metadata panel provides context without cluttering your editing space.`
      },
      {
        id: '1-2',
        name: 'api-reference.md',
        type: 'file',
        path: '/docs/api-reference.md',
        extension: 'md',
        size: 4123,
        lastModified: '2026-02-03T09:15:00Z',
        content: `# API Reference

## File Operations

### Create File

\`\`\`typescript
async function createFile(path: string, content: string): Promise<FileNode>
\`\`\`

Creates a new file at the specified path. Directories are created automatically.

**Parameters:**
- \`path\`: Full path including filename (e.g., "/docs/new-file.md")
- \`content\`: Initial content of the file

**Returns:** The created FileNode object

### Read File

\`\`\`typescript
async function readFile(path: string): Promise<string>
\`\`\`

Reads the content of a file.

### Update File

\`\`\`typescript
async function updateFile(path: string, content: string): Promise<void>
\`\`\`

Updates the content of an existing file.

### Delete File

\`\`\`typescript
async function deleteFile(path: string): Promise<void>
\`\`\`

Permanently deletes a file. This action requires confirmation.

## Search Operations

### Search Files

\`\`\`typescript
function searchFiles(query: string): Promise<FileNode[]>
\`\`\`

Searches through file names and returns matching results.`
      },
      {
        id: '1-3',
        name: 'mermaid-diagrams.md',
        type: 'file',
        path: '/docs/mermaid-diagrams.md',
        extension: 'md',
        size: 8942,
        lastModified: '2026-03-13T10:30:00Z',
        content: mermaidDemoContent
      }
    ]
  },
  {
    id: '2',
    name: 'projects',
    type: 'folder',
    path: '/projects',
    children: [
      {
        id: '2-1',
        name: 'website-redesign',
        type: 'folder',
        path: '/projects/website-redesign',
        children: [
          {
            id: '2-1-1',
            name: 'api-spec.json',
            type: 'file',
            path: '/projects/website-redesign/api-spec.json',
            extension: 'json',
            size: 5842,
            lastModified: '2026-03-15T14:20:00Z',
            content: `{
  "openapi": "3.0.0",
  "info": {
    "title": "Stash-MCP API",
    "description": "API for managing documents and files in the Stash-MCP system",
    "version": "1.0.0",
    "contact": {
      "name": "API Support",
      "email": "support@stash-mcp.dev"
    }
  },
  "servers": [
    {
      "url": "https://api.stash-mcp.dev/v1",
      "description": "Production server"
    }
  ],
  "paths": {
    "/documents": {
      "get": {
        "summary": "List all documents",
        "description": "Retrieve a list of all documents in the system",
        "tags": ["Documents"],
        "parameters": [
          {
            "name": "limit",
            "in": "query",
            "description": "Maximum number of documents to return",
            "schema": {
              "type": "integer",
              "default": 50,
              "maximum": 100
            }
          },
          {
            "name": "offset",
            "in": "query",
            "description": "Number of documents to skip",
            "schema": {
              "type": "integer",
              "default": 0
            }
          }
        ],
        "responses": {
          "200": {
            "description": "Successful response",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "properties": {
                    "documents": {
                      "type": "array",
                      "items": {
                        "type": "object",
                        "properties": {
                          "id": {
                            "type": "string",
                            "example": "doc-123"
                          },
                          "name": {
                            "type": "string",
                            "example": "getting-started.md"
                          },
                          "path": {
                            "type": "string",
                            "example": "/docs/getting-started.md"
                          },
                          "extension": {
                            "type": "string",
                            "example": "md"
                          },
                          "size": {
                            "type": "integer",
                            "example": 2048
                          },
                          "lastModified": {
                            "type": "string",
                            "format": "date-time",
                            "example": "2026-03-15T14:20:00Z"
                          }
                        }
                      }
                    },
                    "total": {
                      "type": "integer",
                      "example": 42
                    }
                  }
                },
                "example": {
                  "documents": [
                    {
                      "id": "doc-123",
                      "name": "getting-started.md",
                      "path": "/docs/getting-started.md",
                      "extension": "md",
                      "size": 2048,
                      "lastModified": "2026-03-15T14:20:00Z"
                    }
                  ],
                  "total": 1
                }
              }
            }
          }
        }
      },
      "post": {
        "summary": "Create a new document",
        "description": "Create a new document in the system",
        "tags": ["Documents"],
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "required": ["name", "path", "extension"],
                "properties": {
                  "name": {
                    "type": "string",
                    "example": "new-document.md"
                  },
                  "path": {
                    "type": "string",
                    "example": "/docs/new-document.md"
                  },
                  "content": {
                    "type": "string",
                    "example": "# New Document"
                  },
                  "extension": {
                    "type": "string",
                    "enum": ["md", "txt", "json"],
                    "example": "md"
                  }
                }
              }
            }
          }
        },
        "responses": {
          "201": {
            "description": "Document created successfully",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "properties": {
                    "id": {
                      "type": "string",
                      "example": "doc-456"
                    },
                    "name": {
                      "type": "string",
                      "example": "new-document.md"
                    },
                    "path": {
                      "type": "string",
                      "example": "/docs/new-document.md"
                    },
                    "extension": {
                      "type": "string",
                      "example": "md"
                    },
                    "createdAt": {
                      "type": "string",
                      "format": "date-time",
                      "example": "2026-03-17T10:30:00Z"
                    }
                  }
                }
              }
            }
          },
          "400": {
            "description": "Invalid input",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "properties": {
                    "error": {
                      "type": "string",
                      "example": "Invalid file extension"
                    }
                  }
                }
              }
            }
          }
        }
      }
    },
    "/documents/{documentId}": {
      "get": {
        "summary": "Get a specific document",
        "description": "Retrieve a document by its ID",
        "tags": ["Documents"],
        "parameters": [
          {
            "name": "documentId",
            "in": "path",
            "required": true,
            "description": "The document ID",
            "schema": {
              "type": "string"
            },
            "example": "doc-123"
          }
        ],
        "responses": {
          "200": {
            "description": "Successful response",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "properties": {
                    "id": {
                      "type": "string",
                      "example": "doc-123"
                    },
                    "name": {
                      "type": "string",
                      "example": "getting-started.md"
                    },
                    "path": {
                      "type": "string",
                      "example": "/docs/getting-started.md"
                    },
                    "content": {
                      "type": "string",
                      "example": "# Getting Started\\n\\nWelcome to Stash-MCP..."
                    },
                    "extension": {
                      "type": "string",
                      "example": "md"
                    },
                    "size": {
                      "type": "integer",
                      "example": 2048
                    }
                  }
                }
              }
            }
          },
          "404": {
            "description": "Document not found"
          }
        }
      },
      "put": {
        "summary": "Update a document",
        "description": "Update an existing document",
        "tags": ["Documents"],
        "parameters": [
          {
            "name": "documentId",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "requestBody": {
          "required": true,
          "content": {
            "application/json": {
              "schema": {
                "type": "object",
                "properties": {
                  "content": {
                    "type": "string",
                    "example": "# Updated Content"
                  },
                  "name": {
                    "type": "string",
                    "example": "updated-name.md"
                  }
                }
              }
            }
          }
        },
        "responses": {
          "200": {
            "description": "Document updated successfully"
          },
          "404": {
            "description": "Document not found"
          }
        }
      },
      "delete": {
        "summary": "Delete a document",
        "description": "Remove a document from the system",
        "tags": ["Documents"],
        "parameters": [
          {
            "name": "documentId",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "responses": {
          "204": {
            "description": "Document deleted successfully"
          },
          "404": {
            "description": "Document not found"
          }
        }
      }
    },
    "/folders": {
      "get": {
        "summary": "List all folders",
        "description": "Retrieve a list of all folders",
        "tags": ["Folders"],
        "responses": {
          "200": {
            "description": "Successful response",
            "content": {
              "application/json": {
                "schema": {
                  "type": "array",
                  "items": {
                    "type": "object",
                    "properties": {
                      "id": {
                        "type": "string",
                        "example": "folder-789"
                      },
                      "name": {
                        "type": "string",
                        "example": "docs"
                      },
                      "path": {
                        "type": "string",
                        "example": "/docs"
                      },
                      "childCount": {
                        "type": "integer",
                        "example": 5
                      }
                    }
                  }
                },
                "example": [
                  {
                    "id": "folder-1",
                    "name": "docs",
                    "path": "/docs",
                    "childCount": 3
                  },
                  {
                    "id": "folder-2",
                    "name": "projects",
                    "path": "/projects",
                    "childCount": 2
                  }
                ]
              }
            }
          }
        }
      }
    }
  }
}`
          },
          {
            id: '2-1-2',
            name: 'notes.md',
            type: 'file',
            path: '/projects/website-redesign/notes.md',
            extension: 'md',
            size: 1432,
            lastModified: '2026-02-06T11:45:00Z',
            content: `# Website Redesign Notes

## Meeting - Feb 6, 2026

**Attendees:** Design team, Engineering leads

### Key Decisions

- Moving to a more modern, minimal aesthetic
- Prioritizing mobile-first responsive design
- New color palette: deep blues with coral accents
- Typography: Inter for UI, Merriweather for content

### Action Items

- [ ] Create high-fidelity mockups
- [ ] Set up design system in Figma
- [ ] Begin component library development
- [ ] Performance audit of current site

### Timeline

- **Week 1-2**: Design phase
- **Week 3-4**: Development sprint 1
- **Week 5-6**: Testing and refinement
- **Week 7**: Launch preparation`
          },
          {
            id: '2-1-3',
            name: 'requirements.txt',
            type: 'file',
            path: '/projects/website-redesign/requirements.txt',
            extension: 'txt',
            size: 524,
            lastModified: '2026-02-01T16:20:00Z',
            content: `Website Redesign Requirements

MUST HAVE:
- Responsive design (mobile, tablet, desktop)
- Accessibility compliance (WCAG 2.1 AA)
- Fast load times (<2s)
- SEO optimization
- Contact form functionality
- Blog section with markdown support

NICE TO HAVE:
- Dark mode toggle
- Animation transitions
- Newsletter signup
- Search functionality
- Multilingual support`
          }
        ]
      },
      {
        id: '2-2',
        name: 'api-integration',
        type: 'folder',
        path: '/projects/api-integration',
        children: [
          {
            id: '2-2-1',
            name: 'spec.json',
            type: 'file',
            path: '/projects/api-integration/spec.json',
            extension: 'json',
            size: 892,
            lastModified: '2026-01-28T13:10:00Z',
            content: `{
  "openapi": "3.0.0",
  "info": {
    "title": "File Storage API",
    "version": "1.0.0",
    "description": "Simple file storage and retrieval API"
  },
  "servers": [
    {
      "url": "https://api.stash-mcp.example.com/v1"
    }
  ],
  "paths": {
    "/files": {
      "get": {
        "summary": "List all files",
        "description": "Retrieve a list of all files in the storage",
        "tags": ["Files"],
        "responses": {
          "200": {
            "description": "Successful response",
            "content": {
              "application/json": {
                "schema": {
                  "type": "array",
                  "items": {
                    "type": "object",
                    "properties": {
                      "id": {
                        "type": "string",
                        "example": "file-001"
                      },
                      "name": {
                        "type": "string",
                        "example": "document.pdf"
                      },
                      "size": {
                        "type": "integer",
                        "example": 1024000
                      },
                      "mimeType": {
                        "type": "string",
                        "example": "application/pdf"
                      },
                      "uploadedAt": {
                        "type": "string",
                        "format": "date-time",
                        "example": "2026-03-17T10:00:00Z"
                      }
                    }
                  }
                },
                "example": [
                  {
                    "id": "file-001",
                    "name": "document.pdf",
                    "size": 1024000,
                    "mimeType": "application/pdf",
                    "uploadedAt": "2026-03-17T10:00:00Z"
                  }
                ]
              }
            }
          }
        }
      },
      "post": {
        "summary": "Upload a file",
        "description": "Upload a new file to storage",
        "tags": ["Files"],
        "requestBody": {
          "required": true,
          "content": {
            "multipart/form-data": {
              "schema": {
                "type": "object",
                "properties": {
                  "file": {
                    "type": "string",
                    "format": "binary",
                    "description": "File to upload"
                  },
                  "metadata": {
                    "type": "object",
                    "properties": {
                      "description": {
                        "type": "string",
                        "example": "Important document"
                      },
                      "tags": {
                        "type": "array",
                        "items": {
                          "type": "string"
                        },
                        "example": ["important", "archive"]
                      }
                    }
                  }
                }
              }
            }
          }
        },
        "responses": {
          "201": {
            "description": "File uploaded successfully",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "properties": {
                    "id": {
                      "type": "string",
                      "example": "file-002"
                    },
                    "url": {
                      "type": "string",
                      "example": "https://storage.example.com/files/file-002"
                    }
                  }
                }
              }
            }
          }
        }
      }
    },
    "/files/{fileId}": {
      "get": {
        "summary": "Get file details",
        "description": "Retrieve details about a specific file",
        "tags": ["Files"],
        "parameters": [
          {
            "name": "fileId",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            },
            "example": "file-001"
          }
        ],
        "responses": {
          "200": {
            "description": "File details",
            "content": {
              "application/json": {
                "schema": {
                  "type": "object",
                  "properties": {
                    "id": {
                      "type": "string",
                      "example": "file-001"
                    },
                    "name": {
                      "type": "string",
                      "example": "document.pdf"
                    },
                    "size": {
                      "type": "integer",
                      "example": 1024000
                    },
                    "downloadUrl": {
                      "type": "string",
                      "example": "https://storage.example.com/download/file-001"
                    }
                  }
                }
              }
            }
          },
          "404": {
            "description": "File not found"
          }
        }
      },
      "delete": {
        "summary": "Delete a file",
        "description": "Remove a file from storage",
        "tags": ["Files"],
        "parameters": [
          {
            "name": "fileId",
            "in": "path",
            "required": true,
            "schema": {
              "type": "string"
            }
          }
        ],
        "responses": {
          "204": {
            "description": "File deleted successfully"
          },
          "404": {
            "description": "File not found"
          }
        }
      }
    }
  }
}`
          }
        ]
      }
    ]
  },
  {
    id: '3',
    name: 'templates',
    type: 'folder',
    path: '/templates',
    children: [
      {
        id: '3-1',
        name: 'meeting-notes.md',
        type: 'file',
        path: '/templates/meeting-notes.md',
        extension: 'md',
        size: 345,
        lastModified: '2026-01-15T10:00:00Z',
        content: `# Meeting Notes - [Date]

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
      {
        id: '3-2',
        name: 'project-brief.md',
        type: 'file',
        path: '/templates/project-brief.md',
        extension: 'md',
        size: 428,
        lastModified: '2026-01-15T10:05:00Z',
        content: `# Project Brief - [Project Name]

## Overview

[Brief description of the project]

## Objectives

- 
- 
- 

## Scope

**In Scope:**
- 

**Out of Scope:**
- 

## Timeline

| Phase | Duration | Deliverable |
|-------|----------|-------------|
|       |          |             |

## Stakeholders

- **Project Lead:** 
- **Team Members:** 
- **Stakeholders:** 

## Success Criteria

1. 
2. 
3. `
      }
    ]
  },
  {
    id: '4',
    name: 'README.md',
    type: 'file',
    path: '/README.md',
    extension: 'md',
    size: 1628,
    lastModified: '2026-02-04T18:30:00Z',
    content: `# Stash-MCP Document Repository

This repository contains all documentation, notes, and project materials managed through Stash-MCP.

## Structure

\`\`\`
/
├── docs/              # General documentation
├── projects/          # Active project materials
├── templates/         # Document templates
└── README.md         # This file
\`\`\`

## Usage

### Viewing Documents

Browse the file tree on the left to find documents. Click any file to view its contents in the center panel.

### Editing Documents

Click the "Edit" tab or pencil icon to switch to edit mode. Changes are auto-saved when you click "Save."

### Creating New Documents

Use the "+ New Document" button at the top of the file tree, or right-click any folder to create a new file in that location.

## Best Practices

1. **Use descriptive filenames**: Make files easy to find with clear, descriptive names
2. **Organize by project**: Keep related documents together in folders
3. **Use markdown**: Take advantage of markdown formatting for readable documents
4. **Regular backups**: Important documents should be backed up regularly

## Tips

- **Search**: Use the search bar at the top of the file tree to quickly filter files
- **Keyboard shortcuts**: Navigate efficiently with keyboard shortcuts
- **Templates**: Start with a template for common document types

---

*Last updated: February 4, 2026*`
  },
  {
    id: '5',
    name: 'specifications',
    type: 'folder',
    path: '/specifications',
    children: [
      {
        id: '5-1',
        name: 'order-workflow.arazzo.yaml',
        type: 'file',
        path: '/specifications/order-workflow.arazzo.yaml',
        extension: 'yaml',
        size: 4235,
        lastModified: '2026-03-16T09:45:00Z',
        content: `arazzo: 1.0.0
info:
  title: E-Commerce Order Workflow
  version: 1.0.0
  description: |
    Complete order workflow from product selection to order fulfillment.
    Demonstrates how multiple API endpoints work together in a typical e-commerce flow.

sourceDescriptions:
  - name: ecommerce-api
    url: https://api.ecommerce.example.com/openapi.json
    type: openapi

workflows:
  - workflowId: complete-order-flow
    summary: Complete order flow from browsing to fulfillment
    description: |
      This workflow demonstrates the complete lifecycle of an e-commerce order:
      1. Browse products
      2. Add items to cart
      3. Create order
      4. Process payment
      5. Fulfill order
    
    inputs:
      type: object
      properties:
        customerId:
          type: string
          description: Unique customer identifier
        productIds:
          type: array
          items:
            type: string
          description: List of product IDs to purchase
    
    steps:
      - stepId: get-products
        operationId: ecommerce-api.getProducts
        description: Retrieve product catalog
        successCriteria:
          - condition: $statusCode == 200
        outputs:
          availableProducts: $response.body.products
      
      - stepId: check-inventory
        operationId: ecommerce-api.checkInventory
        description: Verify product availability
        dependsOn: get-products
        parameters:
          - name: productIds
            in: query
            value: $inputs.productIds
        successCriteria:
          - condition: $statusCode == 200
          - condition: $response.body.allAvailable == true
        outputs:
          inventoryStatus: $response.body
      
      - stepId: create-cart
        operationId: ecommerce-api.createCart
        description: Initialize shopping cart
        dependsOn: check-inventory
        requestBody:
          contentType: application/json
          payload:
            customerId: $inputs.customerId
            items: $inputs.productIds
        successCriteria:
          - condition: $statusCode == 201
        outputs:
          cartId: $response.body.id
          cartTotal: $response.body.total
      
      - stepId: create-order
        operationId: ecommerce-api.createOrder
        description: Convert cart to order
        dependsOn: create-cart
        requestBody:
          contentType: application/json
          payload:
            cartId: $steps.create-cart.outputs.cartId
            customerId: $inputs.customerId
            shippingAddress:
              street: "123 Main St"
              city: "Springfield"
              state: "IL"
              zipCode: "62701"
        successCriteria:
          - condition: $statusCode == 201
        outputs:
          orderId: $response.body.orderId
          orderTotal: $response.body.total
      
      - stepId: process-payment
        operationId: ecommerce-api.processPayment
        description: Process payment for the order
        dependsOn: create-order
        requestBody:
          contentType: application/json
          payload:
            orderId: $steps.create-order.outputs.orderId
            amount: $steps.create-order.outputs.orderTotal
            paymentMethod:
              type: credit_card
              cardNumber: "4111111111111111"
              expiryMonth: "12"
              expiryYear: "2028"
              cvv: "123"
        successCriteria:
          - condition: $statusCode == 200
          - condition: $response.body.status == "approved"
        outputs:
          paymentId: $response.body.paymentId
          paymentStatus: $response.body.status
      
      - stepId: fulfill-order
        operationId: ecommerce-api.fulfillOrder
        description: Mark order as fulfilled and ready for shipping
        dependsOn: process-payment
        requestBody:
          contentType: application/json
          payload:
            orderId: $steps.create-order.outputs.orderId
            paymentId: $steps.process-payment.outputs.paymentId
        successCriteria:
          - condition: $statusCode == 200
          - condition: $response.body.fulfillmentStatus == "ready_to_ship"
        outputs:
          trackingNumber: $response.body.trackingNumber
          estimatedDelivery: $response.body.estimatedDeliveryDate
    
    outputs:
      orderId: $steps.create-order.outputs.orderId
      paymentId: $steps.process-payment.outputs.paymentId
      trackingNumber: $steps.fulfill-order.outputs.trackingNumber
      totalAmount: $steps.create-order.outputs.orderTotal

  - workflowId: order-cancellation
    summary: Cancel an existing order
    description: Workflow for canceling an order and processing refund
    
    inputs:
      type: object
      properties:
        orderId:
          type: string
          description: Order ID to cancel
        reason:
          type: string
          description: Cancellation reason
    
    steps:
      - stepId: get-order
        operationId: ecommerce-api.getOrder
        description: Retrieve order details
        parameters:
          - name: orderId
            in: path
            value: $inputs.orderId
        successCriteria:
          - condition: $statusCode == 200
        outputs:
          order: $response.body
      
      - stepId: cancel-order
        operationId: ecommerce-api.cancelOrder
        description: Cancel the order
        dependsOn: get-order
        requestBody:
          contentType: application/json
          payload:
            orderId: $inputs.orderId
            reason: $inputs.reason
        successCriteria:
          - condition: $statusCode == 200
        outputs:
          cancellationId: $response.body.cancellationId
      
      - stepId: process-refund
        operationId: ecommerce-api.processRefund
        description: Process refund for canceled order
        dependsOn: cancel-order
        requestBody:
          contentType: application/json
          payload:
            orderId: $inputs.orderId
            amount: $steps.get-order.outputs.order.total
            paymentId: $steps.get-order.outputs.order.paymentId
        successCriteria:
          - condition: $statusCode == 200
          - condition: $response.body.refundStatus == "processed"
        outputs:
          refundId: $response.body.refundId
          refundAmount: $response.body.amount
    
    outputs:
      cancellationId: $steps.cancel-order.outputs.cancellationId
      refundId: $steps.process-refund.outputs.refundId
      refundAmount: $steps.process-refund.outputs.refundAmount`
      },
      {
        id: '5-2',
        name: 'notification-service.asyncapi.yaml',
        type: 'file',
        path: '/specifications/notification-service.asyncapi.yaml',
        extension: 'yaml',
        size: 5124,
        lastModified: '2026-03-16T11:20:00Z',
        content: `asyncapi: 3.0.0
info:
  title: Notification Service
  version: 1.2.0
  description: |
    Event-driven notification service for real-time user notifications.
    Handles user events, order updates, and system alerts.
  contact:
    name: Platform Team
    email: platform@example.com
  license:
    name: Apache 2.0
    url: https://www.apache.org/licenses/LICENSE-2.0

servers:
  production:
    host: notifications.example.com
    protocol: kafka
    description: Production Kafka cluster
    tags:
      - name: env:production
    bindings:
      kafka:
        schemaRegistryUrl: https://schema-registry.example.com
  staging:
    host: notifications-staging.example.com
    protocol: kafka
    description: Staging Kafka cluster
    tags:
      - name: env:staging

channels:
  user/signup:
    address: user.signup.v1
    description: Channel for user signup events
    messages:
      userSignedUp:
        $ref: '#/components/messages/UserSignedUp'
    bindings:
      kafka:
        topic: user.signup.v1
        partitions: 3
        replicas: 2

  order/created:
    address: order.created.v1
    description: Channel for order creation events
    messages:
      orderCreated:
        $ref: '#/components/messages/OrderCreated'
    bindings:
      kafka:
        topic: order.created.v1
        partitions: 5
        replicas: 3

  order/status:
    address: order.status.v1
    description: Channel for order status updates
    messages:
      orderStatusChanged:
        $ref: '#/components/messages/OrderStatusChanged'
    bindings:
      kafka:
        topic: order.status.v1
        partitions: 5
        replicas: 3

  notifications/email:
    address: notifications.email.v1
    description: Channel for email notifications
    messages:
      emailNotification:
        $ref: '#/components/messages/EmailNotification'

  notifications/push:
    address: notifications.push.v1
    description: Channel for push notifications
    messages:
      pushNotification:
        $ref: '#/components/messages/PushNotification'

operations:
  onUserSignup:
    action: receive
    channel:
      $ref: '#/channels/user~1signup'
    summary: Triggered when a new user signs up
    description: |
      Receives user signup events and triggers welcome email and 
      initial notification setup.
    messages:
      - $ref: '#/channels/user~1signup/messages/userSignedUp'

  sendWelcomeEmail:
    action: send
    channel:
      $ref: '#/channels/notifications~1email'
    summary: Send welcome email to new users
    messages:
      - $ref: '#/channels/notifications~1email/messages/emailNotification'

  onOrderCreated:
    action: receive
    channel:
      $ref: '#/channels/order~1created'
    summary: Triggered when an order is created
    messages:
      - $ref: '#/channels/order~1created/messages/orderCreated'

  onOrderStatusChange:
    action: receive
    channel:
      $ref: '#/channels/order~1status'
    summary: Triggered when order status changes
    messages:
      - $ref: '#/channels/order~1status/messages/orderStatusChanged'

  sendOrderNotification:
    action: send
    channel:
      $ref: '#/channels/notifications~1push'
    summary: Send push notification for order updates
    messages:
      - $ref: '#/channels/notifications~1push/messages/pushNotification'

components:
  messages:
    UserSignedUp:
      name: UserSignedUp
      title: User Signed Up Event
      summary: Event published when a new user completes registration
      contentType: application/json
      payload:
        $ref: '#/components/schemas/UserSignedUpPayload'
      examples:
        - payload:
            userId: "usr_1234567890"
            email: "user@example.com"
            username: "johndoe"
            signupMethod: "email"
            timestamp: "2026-03-17T10:30:00Z"

    OrderCreated:
      name: OrderCreated
      title: Order Created Event
      summary: Event published when a new order is created
      contentType: application/json
      payload:
        $ref: '#/components/schemas/OrderCreatedPayload'
      examples:
        - payload:
            orderId: "ord_9876543210"
            customerId: "usr_1234567890"
            items:
              - productId: "prd_111"
                quantity: 2
                price: 29.99
              - productId: "prd_222"
                quantity: 1
                price: 49.99
            total: 109.97
            currency: "USD"
            timestamp: "2026-03-17T11:00:00Z"

    OrderStatusChanged:
      name: OrderStatusChanged
      title: Order Status Changed Event
      summary: Event published when order status changes
      contentType: application/json
      payload:
        $ref: '#/components/schemas/OrderStatusChangedPayload'
      examples:
        - payload:
            orderId: "ord_9876543210"
            previousStatus: "pending"
            currentStatus: "shipped"
            trackingNumber: "TRK123456789"
            timestamp: "2026-03-17T14:30:00Z"

    EmailNotification:
      name: EmailNotification
      title: Email Notification
      summary: Email notification to be sent
      contentType: application/json
      payload:
        $ref: '#/components/schemas/EmailNotificationPayload'

    PushNotification:
      name: PushNotification
      title: Push Notification
      summary: Push notification to be sent to user device
      contentType: application/json
      payload:
        $ref: '#/components/schemas/PushNotificationPayload'

  schemas:
    UserSignedUpPayload:
      type: object
      required:
        - userId
        - email
        - timestamp
      properties:
        userId:
          type: string
          description: Unique user identifier
        email:
          type: string
          format: email
          description: User email address
        username:
          type: string
          description: User's chosen username
        signupMethod:
          type: string
          enum: [email, google, facebook, apple]
          description: Method used for signup
        timestamp:
          type: string
          format: date-time
          description: When the signup occurred

    OrderCreatedPayload:
      type: object
      required:
        - orderId
        - customerId
        - items
        - total
        - timestamp
      properties:
        orderId:
          type: string
          description: Unique order identifier
        customerId:
          type: string
          description: Customer ID who placed the order
        items:
          type: array
          items:
            type: object
            properties:
              productId:
                type: string
              quantity:
                type: integer
              price:
                type: number
        total:
          type: number
          description: Order total amount
        currency:
          type: string
          default: USD
        timestamp:
          type: string
          format: date-time

    OrderStatusChangedPayload:
      type: object
      required:
        - orderId
        - previousStatus
        - currentStatus
        - timestamp
      properties:
        orderId:
          type: string
        previousStatus:
          type: string
          enum: [pending, processing, shipped, delivered, cancelled]
        currentStatus:
          type: string
          enum: [pending, processing, shipped, delivered, cancelled]
        trackingNumber:
          type: string
        estimatedDelivery:
          type: string
          format: date-time
        timestamp:
          type: string
          format: date-time

    EmailNotificationPayload:
      type: object
      required:
        - to
        - subject
        - body
      properties:
        to:
          type: string
          format: email
        subject:
          type: string
        body:
          type: string
        templateId:
          type: string
        templateData:
          type: object

    PushNotificationPayload:
      type: object
      required:
        - userId
        - title
        - message
      properties:
        userId:
          type: string
        title:
          type: string
        message:
          type: string
        data:
          type: object
        priority:
          type: string
          enum: [low, normal, high]
          default: normal`
      },
      {
        id: '5-3',
        name: 'design-tokens.json',
        type: 'file',
        path: '/specifications/design-tokens.json',
        extension: 'json',
        size: 3842,
        lastModified: '2026-03-16T13:10:00Z',
        content: `{
  "$schema": "https://design-tokens.github.io/community-group/format/schema.json",
  "meta": {
    "name": "Stash-MCP Design System",
    "version": "2.0.0",
    "description": "Design tokens for Stash-MCP application with semi-dark theme optimized for large displays"
  },
  "colors": {
    "$type": "color",
    "base": {
      "$value": "#1e1e2e",
      "$description": "Base background color - deep charcoal with purple tint"
    },
    "surface": {
      "$value": "#272738",
      "$description": "Surface color for panels and cards"
    },
    "surface-elevated": {
      "$value": "#2f2f42",
      "$description": "Elevated surface color for modals and overlays"
    },
    "border": {
      "$value": "#3a3a4d",
      "$description": "Border color for dividers and outlines"
    },
    "border-subtle": {
      "$value": "#2f2f42",
      "$description": "Subtle border color for less prominent divisions"
    },
    "text": {
      "primary": {
        "$value": "#e4e4e7",
        "$description": "Primary text color - light gray"
      },
      "secondary": {
        "$value": "#a1a1aa",
        "$description": "Secondary text color - muted gray"
      },
      "muted": {
        "$value": "#71717a",
        "$description": "Muted text color for less important content"
      },
      "inverse": {
        "$value": "#18181b",
        "$description": "Inverse text color for use on light backgrounds"
      }
    },
    "accent": {
      "teal": {
        "$value": "#94e2d5",
        "$description": "Primary accent - muted teal"
      },
      "teal-dark": {
        "$value": "#76cfc1",
        "$description": "Darker shade of accent teal"
      },
      "blue": {
        "$value": "#89b4fa",
        "$description": "Blue accent for interactive elements"
      },
      "purple": {
        "$value": "#cba6f7",
        "$description": "Purple accent for special highlights"
      },
      "green": {
        "$value": "#a6e3a1",
        "$description": "Green accent for success states"
      },
      "yellow": {
        "$value": "#f9e2af",
        "$description": "Yellow accent for warnings"
      },
      "red": {
        "$value": "#f38ba8",
        "$description": "Red accent for errors and destructive actions"
      }
    },
    "semantic": {
      "success": {
        "$value": "#a6e3a1",
        "$description": "Success state color"
      },
      "warning": {
        "$value": "#f9e2af",
        "$description": "Warning state color"
      },
      "error": {
        "$value": "#f38ba8",
        "$description": "Error state color"
      },
      "info": {
        "$value": "#89b4fa",
        "$description": "Info state color"
      }
    }
  },
  "spacing": {
    "$type": "dimension",
    "xs": {
      "$value": "0.25rem",
      "$description": "Extra small spacing - 4px"
    },
    "sm": {
      "$value": "0.5rem",
      "$description": "Small spacing - 8px"
    },
    "md": {
      "$value": "1rem",
      "$description": "Medium spacing - 16px"
    },
    "lg": {
      "$value": "1.5rem",
      "$description": "Large spacing - 24px"
    },
    "xl": {
      "$value": "2rem",
      "$description": "Extra large spacing - 32px"
    },
    "2xl": {
      "$value": "3rem",
      "$description": "2X large spacing - 48px"
    }
  },
  "typography": {
    "font-family": {
      "$type": "fontFamily",
      "sans": {
        "$value": ["Inter", "-apple-system", "BlinkMacSystemFont", "sans-serif"],
        "$description": "Primary sans-serif font stack"
      },
      "mono": {
        "$value": ["JetBrains Mono", "Consolas", "Monaco", "monospace"],
        "$description": "Monospace font stack for code"
      }
    },
    "font-size": {
      "$type": "dimension",
      "xs": {
        "$value": "0.75rem",
        "$description": "12px"
      },
      "sm": {
        "$value": "0.875rem",
        "$description": "14px"
      },
      "base": {
        "$value": "1rem",
        "$description": "16px"
      },
      "lg": {
        "$value": "1.125rem",
        "$description": "18px"
      },
      "xl": {
        "$value": "1.25rem",
        "$description": "20px"
      },
      "2xl": {
        "$value": "1.5rem",
        "$description": "24px"
      },
      "3xl": {
        "$value": "1.875rem",
        "$description": "30px"
      },
      "4xl": {
        "$value": "2.25rem",
        "$description": "36px"
      }
    },
    "font-weight": {
      "$type": "fontWeight",
      "normal": {
        "$value": "400",
        "$description": "Normal weight"
      },
      "medium": {
        "$value": "500",
        "$description": "Medium weight"
      },
      "semibold": {
        "$value": "600",
        "$description": "Semi-bold weight"
      },
      "bold": {
        "$value": "700",
        "$description": "Bold weight"
      }
    },
    "line-height": {
      "$type": "number",
      "tight": {
        "$value": "1.25",
        "$description": "Tight line height"
      },
      "normal": {
        "$value": "1.5",
        "$description": "Normal line height"
      },
      "relaxed": {
        "$value": "1.75",
        "$description": "Relaxed line height"
      }
    }
  },
  "border-radius": {
    "$type": "dimension",
    "none": {
      "$value": "0",
      "$description": "No border radius"
    },
    "sm": {
      "$value": "0.25rem",
      "$description": "Small border radius - 4px"
    },
    "md": {
      "$value": "0.5rem",
      "$description": "Medium border radius - 8px"
    },
    "lg": {
      "$value": "0.75rem",
      "$description": "Large border radius - 12px"
    },
    "xl": {
      "$value": "1rem",
      "$description": "Extra large border radius - 16px"
    },
    "full": {
      "$value": "9999px",
      "$description": "Full/pill border radius"
    }
  },
  "shadow": {
    "$type": "shadow",
    "sm": {
      "$value": {
        "offsetX": "0px",
        "offsetY": "1px",
        "blur": "2px",
        "spread": "0px",
        "color": "rgba(0, 0, 0, 0.25)"
      },
      "$description": "Small shadow"
    },
    "md": {
      "$value": {
        "offsetX": "0px",
        "offsetY": "4px",
        "blur": "6px",
        "spread": "-1px",
        "color": "rgba(0, 0, 0, 0.3)"
      },
      "$description": "Medium shadow"
    },
    "lg": {
      "$value": {
        "offsetX": "0px",
        "offsetY": "10px",
        "blur": "15px",
        "spread": "-3px",
        "color": "rgba(0, 0, 0, 0.35)"
      },
      "$description": "Large shadow"
    }
  },
  "transition": {
    "$type": "duration",
    "fast": {
      "$value": "150ms",
      "$description": "Fast transition duration"
    },
    "normal": {
      "$value": "250ms",
      "$description": "Normal transition duration"
    },
    "slow": {
      "$value": "350ms",
      "$description": "Slow transition duration"
    }
  }
}`
      },
      {
        id: '5-4',
        name: 'button-contract.json',
        type: 'file',
        path: '/specifications/button-contract.json',
        extension: 'json',
        size: 2834,
        lastModified: '2026-03-16T15:30:00Z',
        content: `{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "contract": {
    "name": "Button",
    "version": "2.1.0",
    "description": "Standard button component contract with variant support and accessibility requirements",
    "category": "interactive"
  },
  "interface": {
    "props": {
      "variant": {
        "type": "string",
        "enum": ["primary", "secondary", "outline", "ghost", "destructive"],
        "default": "primary",
        "description": "Visual variant of the button",
        "required": false
      },
      "size": {
        "type": "string",
        "enum": ["sm", "md", "lg"],
        "default": "md",
        "description": "Size variant of the button",
        "required": false
      },
      "disabled": {
        "type": "boolean",
        "default": false,
        "description": "Whether the button is disabled",
        "required": false
      },
      "loading": {
        "type": "boolean",
        "default": false,
        "description": "Whether the button is in loading state",
        "required": false
      },
      "icon": {
        "type": "ReactNode",
        "description": "Optional icon to display in the button",
        "required": false
      },
      "iconPosition": {
        "type": "string",
        "enum": ["left", "right"],
        "default": "left",
        "description": "Position of the icon relative to text",
        "required": false
      },
      "fullWidth": {
        "type": "boolean",
        "default": false,
        "description": "Whether button should take full width of container",
        "required": false
      },
      "onClick": {
        "type": "function",
        "signature": "(event: MouseEvent) => void",
        "description": "Click event handler",
        "required": false
      },
      "type": {
        "type": "string",
        "enum": ["button", "submit", "reset"],
        "default": "button",
        "description": "HTML button type attribute",
        "required": false
      },
      "ariaLabel": {
        "type": "string",
        "description": "Accessible label for screen readers",
        "required": false
      },
      "children": {
        "type": "ReactNode",
        "description": "Button content (text or elements)",
        "required": true
      }
    },
    "events": {
      "onClick": {
        "description": "Fired when button is clicked",
        "payload": {
          "event": "MouseEvent"
        }
      },
      "onFocus": {
        "description": "Fired when button receives focus",
        "payload": {
          "event": "FocusEvent"
        }
      },
      "onBlur": {
        "description": "Fired when button loses focus",
        "payload": {
          "event": "FocusEvent"
        }
      }
    },
    "slots": {
      "default": {
        "description": "Main content slot for button text/elements"
      },
      "icon": {
        "description": "Optional slot for icon element"
      },
      "loader": {
        "description": "Optional slot for custom loading indicator"
      }
    }
  },
  "behavior": {
    "states": {
      "default": {
        "description": "Default interactive state"
      },
      "hover": {
        "description": "Hover state when cursor is over button",
        "triggers": ["mouseenter"]
      },
      "active": {
        "description": "Active state when button is pressed",
        "triggers": ["mousedown"]
      },
      "focus": {
        "description": "Focus state for keyboard navigation",
        "triggers": ["focus"]
      },
      "disabled": {
        "description": "Disabled state - no interaction allowed",
        "conditions": ["props.disabled === true"]
      },
      "loading": {
        "description": "Loading state - interaction prevented",
        "conditions": ["props.loading === true"]
      }
    },
    "interactions": {
      "click": {
        "description": "Handle click events",
        "conditions": ["!disabled", "!loading"],
        "actions": ["emit onClick event"]
      },
      "keydown": {
        "description": "Handle keyboard activation (Space/Enter)",
        "keys": ["Space", "Enter"],
        "conditions": ["!disabled", "!loading"],
        "actions": ["emit onClick event"]
      }
    }
  },
  "accessibility": {
    "required": {
      "role": "button",
      "tabIndex": 0,
      "ariaDisabled": "when disabled prop is true",
      "ariaBusy": "when loading prop is true"
    },
    "recommended": {
      "ariaLabel": "when button only contains icon",
      "ariaPressed": "for toggle buttons",
      "focusVisible": "show visible focus indicator"
    },
    "keyboardSupport": {
      "Space": "Activate button",
      "Enter": "Activate button",
      "Tab": "Move focus to/from button"
    }
  },
  "styling": {
    "variants": {
      "primary": {
        "background": "colors.accent.teal",
        "text": "colors.text.inverse",
        "hover": {
          "background": "colors.accent.teal-dark"
        }
      },
      "secondary": {
        "background": "colors.surface-elevated",
        "text": "colors.text.primary",
        "border": "colors.border"
      },
      "outline": {
        "background": "transparent",
        "text": "colors.text.primary",
        "border": "colors.border"
      },
      "ghost": {
        "background": "transparent",
        "text": "colors.text.primary"
      },
      "destructive": {
        "background": "colors.semantic.error",
        "text": "colors.text.inverse"
      }
    },
    "sizes": {
      "sm": {
        "height": "2rem",
        "padding": "0.5rem 0.75rem",
        "fontSize": "typography.font-size.sm"
      },
      "md": {
        "height": "2.5rem",
        "padding": "0.625rem 1rem",
        "fontSize": "typography.font-size.base"
      },
      "lg": {
        "height": "3rem",
        "padding": "0.75rem 1.5rem",
        "fontSize": "typography.font-size.lg"
      }
    },
    "tokens": [
      "colors.accent.teal",
      "colors.surface-elevated",
      "colors.border",
      "spacing.sm",
      "spacing.md",
      "border-radius.md",
      "transition.normal"
    ]
  },
  "testing": {
    "scenarios": [
      {
        "name": "Click handling",
        "steps": [
          "Render button with onClick handler",
          "Click button",
          "Verify onClick was called"
        ]
      },
      {
        "name": "Disabled state",
        "steps": [
          "Render button with disabled=true",
          "Attempt to click",
          "Verify onClick was not called"
        ]
      },
      {
        "name": "Loading state",
        "steps": [
          "Render button with loading=true",
          "Verify loading indicator is shown",
          "Verify button is not clickable"
        ]
      },
      {
        "name": "Keyboard navigation",
        "steps": [
          "Render button",
          "Press Tab to focus",
          "Press Enter",
          "Verify onClick was called"
        ]
      }
    ]
  },
  "examples": [
    {
      "name": "Primary button",
      "code": "<Button variant=\\"primary\\" onClick={handleClick}>Submit</Button>"
    },
    {
      "name": "Loading button",
      "code": "<Button loading={true}>Please wait...</Button>"
    },
    {
      "name": "Icon button",
      "code": "<Button icon={<PlusIcon />} iconPosition=\\"left\\">Add Item</Button>"
    }
  ]
}`
      }
    ]
  }
];