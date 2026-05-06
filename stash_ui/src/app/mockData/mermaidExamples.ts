export const mermaidDemoContent = `# Mermaid Diagram Examples

This document demonstrates the Mermaid diagram rendering capabilities in Stash-MCP.

## State Diagram

State diagrams are perfect for visualizing order workflows and application states:

\`\`\`mermaid
stateDiagram-v2
    [*] --> Pending: POST /orders
    Pending --> Confirmed: payment authorised
    Pending --> Cancelled: payment declined or user cancels
    Confirmed --> Processing: warehouse picks items
    Processing --> OnHold: stock discrepancy
    Processing --> Shipped: carrier scan
    Processing --> Processing: stock resolved
    OnHold --> Cancelled: unresolvable
    OnHold --> Processing: user cancels within 15 min
    Shipped --> Delivered: delivery confirmed
    Shipped --> Returned: customer returns
    Returned --> Refunded: refund issued
    Delivered --> [*]
    Refunded --> [*]
    Cancelled --> [*]
\`\`\`

## Pie Chart

Pie charts visualize proportional data, like sprint time allocation:

\`\`\`mermaid
%%{init: {'theme':'dark'}}%%
pie title Actual sprint time allocation
    "Feature development" : 42
    "Bug fixes & tech debt" : 20
    "Code review" : 15
    "Testing & QA" : 13
    "Meetings & planning" : 10
\`\`\`

## Git Graph

Git graphs show branch history and merges:

\`\`\`mermaid
%%{init: {'theme':'dark', 'themeVariables': { 'git0': '#94e2d5', 'git1': '#89dceb', 'git2': '#f38ba8', 'git3': '#f9e2af', 'git4': '#a6adc8'}}}%%
gitGraph
    commit id: "initial"
    branch develop
    checkout develop
    commit id: "base code"
    branch feature/order-api
    checkout feature/order-api
    commit id: "POST /orders"
    commit id: "validation"
    commit id: "unit tests"
    checkout develop
    merge feature/order-api
    branch feature/inventory
    checkout feature/inventory
    commit id: "reserve stock"
    commit id: "rollback logic"
    checkout develop
    merge feature/inventory
    checkout main
    merge develop tag: "v1.1.1"
    checkout develop
    branch hotfix/payment-timeout
    checkout hotfix/payment-timeout
    commit id: "increase timeout"
    checkout main
    merge hotfix/payment-timeout tag: "v1.2.0"
    checkout develop
    commit id: "sync hotfix"
\`\`\`

## Sequence Diagram

Sequence diagrams illustrate interactions between services:

\`\`\`mermaid
sequenceDiagram
    actor Customer
    participant Gateway
    participant Auth
    participant Order svc
    participant Inventory svc
    participant Payment svc
    participant Event bus
    participant Notification svc

    Customer->>Gateway: POST /orders (items, paymentToken)
    Gateway->>Auth: Verify JWT
    Auth-->>Gateway: ✓ userId=42
    Gateway->>Order svc: createOrder(userId, items)
    Order svc->>Inventory svc: reserveStock(items)
    Inventory svc-->>Order svc: ✓ reserved stockId=XY9
    Order svc->>Payment svc: charge(paymentToken, amount)
    Payment svc-->>Order svc: ✓ txId=T34821
    Order svc->>Event bus: OrderConfirmed (orderId, userId)
    Order svc-->>Gateway: 201 Created orderId=ORD-099
    Gateway-->>Customer: 201 OK
    Event bus->>Notification svc: send confirmation email
    Notification svc-->>Customer: Your order is confirmed
\`\`\`

## Flowchart

Flowcharts show system architecture and data flows:

\`\`\`mermaid
flowchart TB
    subgraph Client
        WebApp[Web app]
        MobileApp[Mobile app]
    end

    subgraph API["API layer"]
        Gateway[Gateway :3000]
    end

    subgraph Core["Core services"]
        Auth[Auth service :3001]
        Order[Order service :3002]
        Inventory[Inventory service :3003]
        Payment[Payment service :3004]
        Notification[Notification service :3005]
    end

    subgraph Data
        Redis[Redis cache]
        EventBus[Event bus]
        Postgres[Postgres]
    end

    WebApp --> Gateway
    MobileApp --> Gateway
    Gateway --> Auth
    Gateway --> Order
    Order --> Inventory
    Order --> Payment
    Order --> Redis
    Order --> EventBus
    Auth --> Redis
    EventBus --> Notification
    Inventory --> Postgres
    Order --> Postgres
    Payment --> Postgres
\`\`\`

## Class Diagram

Class diagrams represent object-oriented structures:

\`\`\`mermaid
classDiagram
    class Order {
        +String orderId
        +String userId
        +Date createdAt
        +OrderStatus status
        +List~OrderItem~ items
        +Money totalAmount
        +calculateTotal()
        +addItem(item)
        +removeItem(itemId)
        +cancel()
    }

    class OrderItem {
        +String itemId
        +String productId
        +int quantity
        +Money unitPrice
        +Money getSubtotal()
    }

    class Payment {
        +String paymentId
        +String orderId
        +Money amount
        +PaymentStatus status
        +String transactionId
        +process()
        +refund()
    }

    class Inventory {
        +String stockId
        +String productId
        +int quantityAvailable
        +reserve(quantity)
        +release(stockId)
    }

    Order "1" --> "*" OrderItem
    Order "1" --> "1" Payment
    OrderItem --> Inventory : checks
\`\`\`

## ER Diagram

Entity-relationship diagrams model database schemas:

\`\`\`mermaid
erDiagram
    USER ||--o{ ORDER : places
    USER {
        int userId PK
        string email
        string name
        datetime createdAt
    }
    ORDER ||--|{ ORDER_ITEM : contains
    ORDER {
        int orderId PK
        int userId FK
        string status
        decimal totalAmount
        datetime createdAt
    }
    ORDER_ITEM }o--|| PRODUCT : references
    ORDER_ITEM {
        int orderItemId PK
        int orderId FK
        int productId FK
        int quantity
        decimal unitPrice
    }
    PRODUCT {
        int productId PK
        string name
        string sku
        decimal price
        int stockLevel
    }
    ORDER ||--|| PAYMENT : has
    PAYMENT {
        int paymentId PK
        int orderId FK
        string status
        decimal amount
        string transactionId
        datetime processedAt
    }
\`\`\`

## Timeline

Timeline diagrams show project history:

\`\`\`mermaid
timeline
    title Project Development Timeline
    section Planning
        Q1 2025 : Requirements gathering
               : Architecture design
               : Team formation
    section Development
        Q2 2025 : Core API development
               : Database schema
               : Authentication service
        Q3 2025 : Order service
               : Payment integration
               : Inventory management
    section Testing
        Q4 2025 : Integration testing
               : Load testing
               : Security audit
    section Launch
        Q1 2026 : Beta release
               : Production deployment
               : Monitoring setup
\`\`\`

## Gantt Chart

Gantt charts visualize project schedules and task dependencies:

\`\`\`mermaid
gantt
    title Product Launch Schedule
    dateFormat  YYYY-MM-DD
    section Planning
    Requirements gathering       :done,    req1, 2025-01-01, 2025-01-15
    Architecture design          :done,    arch1, 2025-01-15, 2025-02-01
    section Backend Development
    Authentication service       :active,  auth1, 2025-02-01, 2025-02-20
    Order API                    :         order1, after auth1, 15d
    Payment integration          :         pay1, after order1, 10d
    Inventory management         :         inv1, after order1, 12d
    section Frontend Development
    UI component library         :         ui1, 2025-02-10, 20d
    Order flow screens           :         ux1, after order1, 15d
    Payment screens              :         ux2, after pay1, 8d
    section Testing & Launch
    Integration testing          :crit,    test1, after ux2, 10d
    Load testing                 :crit,    test2, after test1, 5d
    Beta release                 :milestone, beta, after test2, 0d
    Production deployment        :crit,    deploy, after beta, 3d
    Go-live                      :milestone, live, after deploy, 0d
\`\`\`

---

All diagrams are rendered using Mermaid.js and styled to match the Stash-MCP dark theme.
`;