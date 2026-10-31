import type { ReactNode } from 'react';
import { Badge, Group, Text, Title, Button, ThemeIcon } from '@mantine/core';
import { IconArrowUpRight, IconInbox } from '@tabler/icons-react';

export function Panel({title,subtitle,action,children,className=''}:{title?:string;subtitle?:string;action?:ReactNode;children:ReactNode;className?:string}){
 return <section className={`panel ${className}`}>
  {title && <div className="panel-heading"><div><Title order={4}>{title}</Title>{subtitle && <Text size="xs" c="dimmed" mt={4}>{subtitle}</Text>}</div>{action}</div>}
  {children}
 </section>;
}
export function Metric({label,value,detail,icon,color='teal'}:{label:string;value:ReactNode;detail:string;icon:ReactNode;color?:string}){
 return <div className="metric-card"><Group justify="space-between"><Text className="metric-label">{label}</Text><ThemeIcon variant="light" color={color} size={34} radius="md">{icon}</ThemeIcon></Group><div className="metric-value">{value}</div><Text size="xs" c="dimmed">{detail}</Text></div>;
}
export function Empty({title,description,action}:{title:string;description:string;action?:ReactNode}){
 return <div className="empty-state"><ThemeIcon size={52} variant="light" color="gray" radius="xl"><IconInbox size={24}/></ThemeIcon><Title order={4} mt="md">{title}</Title><Text c="dimmed" size="sm" maw={420} mt="xs">{description}</Text>{action && <div className="mt16">{action}</div>}</div>;
}
export function PageHeading({eyebrow,title,description,action}:{eyebrow:string;title:string;description:string;action?:ReactNode}){
 return <div className="page-heading"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{description}</p></div><div className="heading-actions">{action}</div></div>;
}
export function LinkButton({children,onClick}:{children:ReactNode;onClick:()=>void}){
 return <Button variant="subtle" size="xs" rightSection={<IconArrowUpRight size={14}/>} onClick={onClick}>{children}</Button>;
}
export function DemoBadge(){ return <Badge size="sm" variant="light" color="orange">合成演示数据</Badge>; }
