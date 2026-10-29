export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[]

export type Database = {
  public: {
    Tables: {
      library_items: {
        Row: {
          id: string
          user_id: string
          course_id: string
          item_type: "explanation" | "exercise"
          title: string
          content: Json
          source_document_id: string | null
          source_page: number | null
          created_at: string
        }
        Insert: {
          id?: string
          user_id: string
          course_id: string
          item_type: "explanation" | "exercise"
          title: string
          content?: Json
          source_document_id?: string | null
          source_page?: number | null
          created_at?: string
        }
        Update: {
          id?: string
          user_id?: string
          course_id?: string
          item_type?: "explanation" | "exercise"
          title?: string
          content?: Json
          source_document_id?: string | null
          source_page?: number | null
          created_at?: string
        }
        Relationships: []
      }
      notebook_notes: {
        Row: {
          id: string
          user_id: string
          course_id: string | null
          title: string
          topic: string
          content: string
          source_type: "manual" | "explanation" | "exercise"
          source_data: Json
          source_document_id: string | null
          source_page: number | null
          created_at: string
          updated_at: string
        }
        Insert: {
          id?: string
          user_id: string
          course_id?: string | null
          title: string
          topic?: string
          content?: string
          source_type?: "manual" | "explanation" | "exercise"
          source_data?: Json
          source_document_id?: string | null
          source_page?: number | null
          created_at?: string
          updated_at?: string
        }
        Update: {
          id?: string
          user_id?: string
          course_id?: string | null
          title?: string
          topic?: string
          content?: string
          source_type?: "manual" | "explanation" | "exercise"
          source_data?: Json
          source_document_id?: string | null
          source_page?: number | null
          created_at?: string
          updated_at?: string
        }
        Relationships: []
      }
      courses: {
        Row: {
          created_at: string
          description: string | null
          id: string
          name: string
          updated_at: string
          user_id: string
        }
        Insert: {
          created_at?: string
          description?: string | null
          id?: string
          name: string
          updated_at?: string
          user_id: string
        }
        Update: {
          created_at?: string
          description?: string | null
          id?: string
          name?: string
          updated_at?: string
          user_id?: string
        }
        Relationships: []
      }
      documents: {
        Row: {
          course_id: string
          content_hash: string | null
          created_at: string
          file_size: number | null
          filename: string
          id: string
          page_count: number | null
          storage_path: string
          summary_status: string
        }
        Insert: {
          course_id: string
          content_hash?: string | null
          created_at?: string
          file_size?: number | null
          filename: string
          id?: string
          page_count?: number | null
          storage_path: string
          summary_status?: string
        }
        Update: {
          course_id?: string
          content_hash?: string | null
          created_at?: string
          file_size?: number | null
          filename?: string
          id?: string
          page_count?: number | null
          storage_path?: string
          summary_status?: string
        }
        Relationships: [
          {
            foreignKeyName: "documents_course_id_fkey"
            columns: ["course_id"]
            isOneToOne: false
            referencedRelation: "courses"
            referencedColumns: ["id"]
          },
        ]
      }
      document_summaries: {
        Row: {
          id: string
          document_id: string
          course_id: string
          document_version: string
          level: "document" | "section"
          section_index: number | null
          title: string
          summary: string
          page_start: number
          page_end: number
          created_at: string
        }
        Insert: {
          id?: string
          document_id: string
          course_id: string
          document_version: string
          level: "document" | "section"
          section_index?: number | null
          title: string
          summary: string
          page_start: number
          page_end: number
          created_at?: string
        }
        Update: {
          id?: string
          document_id?: string
          course_id?: string
          document_version?: string
          level?: "document" | "section"
          section_index?: number | null
          title?: string
          summary?: string
          page_start?: number
          page_end?: number
          created_at?: string
        }
        Relationships: []
      }
      embeddings: {
        Row: {
          chunk_index: number | null
          content: string
          created_at: string
          document_id: string
          embedding: string | null
          id: string
          metadata: Json | null
          page_number: number | null
        }
        Insert: {
          chunk_index?: number | null
          content: string
          created_at?: string
          document_id: string
          embedding?: string | null
          id?: string
          metadata?: Json | null
          page_number?: number | null
        }
        Update: {
          chunk_index?: number | null
          content?: string
          created_at?: string
          document_id?: string
          embedding?: string | null
          id?: string
          metadata?: Json | null
          page_number?: number | null
        }
        Relationships: [
          {
            foreignKeyName: "embeddings_document_id_fkey"
            columns: ["document_id"]
            isOneToOne: false
            referencedRelation: "documents"
            referencedColumns: ["id"]
          },
        ]
      }
      key_terms: {
        Row: {
          created_at: string
          id: string
          session_id: string
          term: string
        }
        Insert: {
          created_at?: string
          id?: string
          session_id: string
          term: string
        }
        Update: {
          created_at?: string
          id?: string
          session_id?: string
          term?: string
        }
        Relationships: [
          {
            foreignKeyName: "key_terms_session_id_fkey"
            columns: ["session_id"]
            isOneToOne: false
            referencedRelation: "sessions"
            referencedColumns: ["id"]
          },
        ]
      }
      messages: {
        Row: {
          content: string
          created_at: string
          id: string
          metadata: Json | null
          role: string
          session_id: string
        }
        Insert: {
          content: string
          created_at?: string
          id?: string
          metadata?: Json | null
          role: string
          session_id: string
        }
        Update: {
          content?: string
          created_at?: string
          id?: string
          metadata?: Json | null
          role?: string
          session_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "messages_session_id_fkey"
            columns: ["session_id"]
            isOneToOne: false
            referencedRelation: "sessions"
            referencedColumns: ["id"]
          },
        ]
      }
      sessions: {
        Row: {
          course_id: string
          created_at: string
          id: string
          language: string
          title: string | null
          updated_at: string
        }
        Insert: {
          course_id: string
          created_at?: string
          id?: string
          language?: string
          title?: string | null
          updated_at?: string
        }
        Update: {
          course_id?: string
          created_at?: string
          id?: string
          language?: string
          title?: string | null
          updated_at?: string
        }
        Relationships: [
          {
            foreignKeyName: "sessions_course_id_fkey"
            columns: ["course_id"]
            isOneToOne: false
            referencedRelation: "courses"
            referencedColumns: ["id"]
          },
        ]
      }
    }
    Views: {
      [_ in never]: never
    }
    Functions: {
      match_embeddings: {
        Args: {
          query_embedding: string
          match_count?: number
          filter_course_id?: string
        }
        Returns: {
          id: string
          content: string
          document_id: string
          page_number: number
          chunk_index: number
          filename: string
          similarity: number
        }[]
      }
    }
    Enums: {
      [_ in never]: never
    }
    CompositeTypes: {
      [_ in never]: never
    }
  }
}

type DefaultSchema = Database[Extract<keyof Database, "public">]

export type Tables<
  DefaultSchemaTableNameOrOptions extends
    | keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
    | { schema: keyof Database },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof Database
  }
    ? keyof (Database[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
        Database[DefaultSchemaTableNameOrOptions["schema"]]["Views"])
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof Database
}
  ? (Database[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
      Database[DefaultSchemaTableNameOrOptions["schema"]]["Views"])[TableName] extends {
      Row: infer R
    }
    ? R
    : never
  : DefaultSchemaTableNameOrOptions extends keyof (DefaultSchema["Tables"] &
        DefaultSchema["Views"])
    ? (DefaultSchema["Tables"] &
        DefaultSchema["Views"])[DefaultSchemaTableNameOrOptions] extends {
        Row: infer R
      }
      ? R
      : never
    : never

export type TablesInsert<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof Database },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof Database
  }
    ? keyof Database[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof Database
}
  ? Database[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Insert: infer I
    }
    ? I
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Insert: infer I
      }
      ? I
      : never
    : never

export type TablesUpdate<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof Database },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof Database
  }
    ? keyof Database[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof Database
}
  ? Database[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Update: infer U
    }
    ? U
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Update: infer U
      }
      ? U
      : never
    : never

export type Enums<
  DefaultSchemaEnumNameOrOptions extends
    | keyof DefaultSchema["Enums"]
    | { schema: keyof Database },
  EnumName extends DefaultSchemaEnumNameOrOptions extends {
    schema: keyof Database
  }
    ? keyof Database[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"]
    : never = never,
> = DefaultSchemaEnumNameOrOptions extends {
  schema: keyof Database
}
  ? Database[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"][EnumName]
  : DefaultSchemaEnumNameOrOptions extends keyof DefaultSchema["Enums"]
    ? DefaultSchema["Enums"][DefaultSchemaEnumNameOrOptions]
    : never
