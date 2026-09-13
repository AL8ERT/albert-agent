/**
 * SSE（Server-Sent Events）流解析器。
 *
 * fetch 返回的是任意分块的字节流，一次读取可能包含多个事件、也可能把事件截断。
 * 因此这里维护一个字符串缓冲：
 *   1. 每次读到数据先追加到 buffer；
 *   2. 按空行（\n\n）切分出完整的事件块，最后一段留在 buffer 里等待后续数据；
 *   3. 从每个事件块中取出以 "data:" 开头的行，去掉前缀后作为一条消息 yield 出去。
 */

export async function* parseSseStream(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<string> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      // stream: true 让 TextDecoder 正确处理跨分块的多字节字符（如中文）
      buffer += decoder.decode(value, { stream: true })
      const blocks = buffer.split('\n\n')
      // 最后一个元素可能是不完整的事件，留待下次读取
      buffer = blocks.pop() ?? ''

      for (const block of blocks) {
        const dataLine = block
          .split('\n')
          .find((line) => line.startsWith('data:'))
        if (dataLine) {
          yield dataLine.slice(5).trim()
        }
      }
    }
  } finally {
    // 无论正常结束还是异常/取消，都释放 reader，避免流被占用
    reader.releaseLock()
  }
}
