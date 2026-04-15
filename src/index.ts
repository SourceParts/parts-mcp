#!/usr/bin/env node

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  Tool,
} from "@modelcontextprotocol/sdk/types.js";
import { SourcePartsSDK } from "@sourceparts/sdk";
import { config } from "dotenv";

// Load environment variables
config();

// Initialize Source Parts SDK
const sdk = new SourcePartsSDK({
  apiKey: process.env.SOURCE_PARTS_API_KEY || "",
  baseUrl: process.env.SOURCE_PARTS_API_URL || "https://source.parts",
  accessToken: process.env.SOURCE_PARTS_ACCESS_TOKEN,
});

// Tool Definitions
const TOOLS: Tool[] = [
  {
    name: "search_products",
    description: "Search for electronic components and products in the Source Parts marketplace. Supports keyword search, category filtering, and pagination.",
    inputSchema: {
      type: "object",
      properties: {
        query: {
          type: "string",
          description: "Search query (keywords, part numbers, descriptions)",
        },
        category: {
          type: "string",
          description: "Optional category filter (e.g., 'resistors', 'capacitors', 'ics')",
        },
        manufacturer: {
          type: "string",
          description: "Optional manufacturer filter",
        },
        minPrice: {
          type: "number",
          description: "Minimum price filter",
        },
        maxPrice: {
          type: "number",
          description: "Maximum price filter",
        },
        inStock: {
          type: "boolean",
          description: "Filter for in-stock items only",
        },
        limit: {
          type: "number",
          description: "Maximum number of results (default: 20, max: 100)",
          default: 20,
        },
        offset: {
          type: "number",
          description: "Pagination offset (default: 0)",
          default: 0,
        },
      },
      required: [],
    },
  },
  {
    name: "get_product_details",
    description: "Get detailed information about a specific product by its SKU, including specifications, pricing, availability, and datasheets.",
    inputSchema: {
      type: "object",
      properties: {
        sku: {
          type: "string",
          description: "The product SKU",
        },
      },
      required: ["sku"],
    },
  },
  {
    name: "get_categories",
    description: "Get the list of available product categories.",
    inputSchema: {
      type: "object",
      properties: {},
    },
  },
  {
    name: "get_manufacturers",
    description: "Get the list of available manufacturers.",
    inputSchema: {
      type: "object",
      properties: {},
    },
  },
  {
    name: "list_quotes",
    description: "List quotes with pagination and filtering.",
    inputSchema: {
      type: "object",
      properties: {
        page: {
          type: "number",
          description: "Page number (default: 1)",
          default: 1,
        },
        limit: {
          type: "number",
          description: "Items per page (default: 20)",
          default: 20,
        },
      },
    },
  },
  {
    name: "get_quote",
    description: "Get detailed information about a specific quote.",
    inputSchema: {
      type: "object",
      properties: {
        quoteId: {
          type: "string",
          description: "The quote ID",
        },
      },
      required: ["quoteId"],
    },
  },
  {
    name: "create_quote",
    description: "Create a new quote with line items.",
    inputSchema: {
      type: "object",
      properties: {
        items: {
          type: "array",
          description: "Array of quote items",
          items: {
            type: "object",
            properties: {
              sku: {
                type: "string",
                description: "Product SKU",
              },
              quantity: {
                type: "number",
                description: "Quantity",
              },
              description: {
                type: "string",
                description: "Optional item description",
              },
            },
            required: ["sku", "quantity"],
          },
        },
        customerId: {
          type: "string",
          description: "Optional customer ID",
        },
        notes: {
          type: "string",
          description: "Optional notes",
        },
      },
      required: ["items"],
    },
  },
  {
    name: "list_boms",
    description: "List BOMs (Bills of Materials) with pagination.",
    inputSchema: {
      type: "object",
      properties: {
        page: {
          type: "number",
          description: "Page number (default: 1)",
          default: 1,
        },
        limit: {
          type: "number",
          description: "Items per page (default: 20)",
          default: 20,
        },
      },
    },
  },
  {
    name: "get_bom",
    description: "Get detailed information about a specific BOM.",
    inputSchema: {
      type: "object",
      properties: {
        bomId: {
          type: "string",
          description: "The BOM ID",
        },
      },
      required: ["bomId"],
    },
  },
  {
    name: "get_bom_pricing",
    description: "Get pricing information for a BOM.",
    inputSchema: {
      type: "object",
      properties: {
        bomId: {
          type: "string",
          description: "The BOM ID",
        },
      },
      required: ["bomId"],
    },
  },
  {
    name: "list_orders",
    description: "List orders with pagination and filtering.",
    inputSchema: {
      type: "object",
      properties: {
        status: {
          type: "string",
          description: "Optional status filter (pending, processing, shipped, delivered, cancelled)",
        },
        page: {
          type: "number",
          description: "Page number (default: 1)",
          default: 1,
        },
        limit: {
          type: "number",
          description: "Items per page (default: 20)",
          default: 20,
        },
      },
    },
  },
  {
    name: "get_order",
    description: "Get detailed information about a specific order.",
    inputSchema: {
      type: "object",
      properties: {
        orderId: {
          type: "string",
          description: "The order ID",
        },
      },
      required: ["orderId"],
    },
  },
  {
    name: "get_order_tracking",
    description: "Get tracking information for an order.",
    inputSchema: {
      type: "object",
      properties: {
        orderId: {
          type: "string",
          description: "The order ID",
        },
      },
      required: ["orderId"],
    },
  },
];

// Tool Handlers
async function handleSearchProducts(args: any): Promise<string> {
  try {
    const result = await sdk.products.search(args);
    return JSON.stringify(result, null, 2);
  } catch (error) {
    return `Error searching products: ${error instanceof Error ? error.message : "Unknown error"}`;
  }
}

async function handleGetProductDetails(args: any): Promise<string> {
  try {
    const product = await sdk.products.get(args.sku);
    return JSON.stringify(product, null, 2);
  } catch (error) {
    return `Error fetching product details: ${error instanceof Error ? error.message : "Unknown error"}`;
  }
}

async function handleGetCategories(): Promise<string> {
  try {
    const categories = await sdk.products.getCategories();
    return JSON.stringify({ categories }, null, 2);
  } catch (error) {
    return `Error fetching categories: ${error instanceof Error ? error.message : "Unknown error"}`;
  }
}

async function handleGetManufacturers(): Promise<string> {
  try {
    const manufacturers = await sdk.products.getManufacturers();
    return JSON.stringify({ manufacturers }, null, 2);
  } catch (error) {
    return `Error fetching manufacturers: ${error instanceof Error ? error.message : "Unknown error"}`;
  }
}

async function handleListQuotes(args: any): Promise<string> {
  try {
    const result = await sdk.quotes.list(args);
    return JSON.stringify(result, null, 2);
  } catch (error) {
    return `Error listing quotes: ${error instanceof Error ? error.message : "Unknown error"}`;
  }
}

async function handleGetQuote(args: any): Promise<string> {
  try {
    const quote = await sdk.quotes.get(args.quoteId);
    return JSON.stringify(quote, null, 2);
  } catch (error) {
    return `Error fetching quote: ${error instanceof Error ? error.message : "Unknown error"}`;
  }
}

async function handleCreateQuote(args: any): Promise<string> {
  try {
    const quote = await sdk.quotes.create(args);
    return JSON.stringify(quote, null, 2);
  } catch (error) {
    return `Error creating quote: ${error instanceof Error ? error.message : "Unknown error"}`;
  }
}

async function handleListBoms(args: any): Promise<string> {
  try {
    const result = await sdk.bom.list(args);
    return JSON.stringify(result, null, 2);
  } catch (error) {
    return `Error listing BOMs: ${error instanceof Error ? error.message : "Unknown error"}`;
  }
}

async function handleGetBom(args: any): Promise<string> {
  try {
    const bom = await sdk.bom.get(args.bomId);
    return JSON.stringify(bom, null, 2);
  } catch (error) {
    return `Error fetching BOM: ${error instanceof Error ? error.message : "Unknown error"}`;
  }
}

async function handleGetBomPricing(args: any): Promise<string> {
  try {
    const pricing = await sdk.bom.getPricing(args.bomId);
    return JSON.stringify(pricing, null, 2);
  } catch (error) {
    return `Error fetching BOM pricing: ${error instanceof Error ? error.message : "Unknown error"}`;
  }
}

async function handleListOrders(args: any): Promise<string> {
  try {
    const result = await sdk.orders.list(args);
    return JSON.stringify(result, null, 2);
  } catch (error) {
    return `Error listing orders: ${error instanceof Error ? error.message : "Unknown error"}`;
  }
}

async function handleGetOrder(args: any): Promise<string> {
  try {
    const order = await sdk.orders.get(args.orderId);
    return JSON.stringify(order, null, 2);
  } catch (error) {
    return `Error fetching order: ${error instanceof Error ? error.message : "Unknown error"}`;
  }
}

async function handleGetOrderTracking(args: any): Promise<string> {
  try {
    const tracking = await sdk.orders.getTracking(args.orderId);
    return JSON.stringify(tracking, null, 2);
  } catch (error) {
    return `Error fetching order tracking: ${error instanceof Error ? error.message : "Unknown error"}`;
  }
}

// Main Server
async function main() {
  const server = new Server(
    {
      name: "sourceparts-mcp",
      version: "0.2.0",
    },
    {
      capabilities: {
        tools: {},
      },
    }
  );

  // Handle tool listing
  server.setRequestHandler(ListToolsRequestSchema, async () => {
    return { tools: TOOLS };
  });

  // Handle tool execution
  server.setRequestHandler(
    CallToolRequestSchema,
    async (request: { params: { name: string; arguments?: Record<string, unknown> } }) => {
    const { name, arguments: args } = request.params;

    try {
      let result: string;

      switch (name) {
        case "search_products":
          result = await handleSearchProducts(args);
          break;
        case "get_product_details":
          result = await handleGetProductDetails(args);
          break;
        case "get_categories":
          result = await handleGetCategories();
          break;
        case "get_manufacturers":
          result = await handleGetManufacturers();
          break;
        case "list_quotes":
          result = await handleListQuotes(args);
          break;
        case "get_quote":
          result = await handleGetQuote(args);
          break;
        case "create_quote":
          result = await handleCreateQuote(args);
          break;
        case "list_boms":
          result = await handleListBoms(args);
          break;
        case "get_bom":
          result = await handleGetBom(args);
          break;
        case "get_bom_pricing":
          result = await handleGetBomPricing(args);
          break;
        case "list_orders":
          result = await handleListOrders(args);
          break;
        case "get_order":
          result = await handleGetOrder(args);
          break;
        case "get_order_tracking":
          result = await handleGetOrderTracking(args);
          break;
        default:
          throw new Error(`Unknown tool: ${name}`);
      }

      return {
        content: [{ type: "text", text: result }],
      };
    } catch (error) {
      return {
        content: [
          {
            type: "text",
            text: `Error: ${error instanceof Error ? error.message : "Unknown error"}`,
          },
        ],
        isError: true,
      };
    }
  });

  // Start server
  const transport = new StdioServerTransport();
  await server.connect(transport);

  console.error("Source Parts MCP Server running on stdio (using @sourceparts/sdk)");
}

main().catch((error) => {
  console.error("Fatal error:", error);
  process.exit(1);
});
